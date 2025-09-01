import asyncio
import json
import logging
import time
#import pickle
import socket
from event_dispatcher import dispatcher
from dataclasses import dataclass
from typing import Optional, Dict, Any
import struct
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def lane_call():
	with open('settings.json') as f:
		return json.load(f)
		
lane_settings = lane_call()
LaneID = lane_settings["Lane"]

@dataclass
class LaneConnectionConfig:
	lane_id: str
	eth_ip: str
	eth_port: int
	peer_ip: Optional[str] = None
	peer_port: Optional[int] = None

class P2PLaneConnection:
	def __init__(self, config: LaneConnectionConfig):
		self.config = config
		self.reader: Optional[asyncio.StreamReader] = None
		self.writer: Optional[asyncio.StreamWriter] = None
		self.connected = asyncio.Event()
		self.running = False
		self._shutdown = asyncio.Event()
		self.data_callback = None
		
	async def start_server(self):
		"""Start listening for peer connection"""
		try:
			server = await asyncio.start_server(
				self._handle_peer_connection,
				self.config.eth_ip,
				self.config.eth_port
			)
			logger.info(f"P2P server started on {self.config.eth_ip}:{self.config.eth_port}")
			return server
		except Exception as e:
			logger.error(f"Failed to start P2P server: {e}")
			return None

	async def connect_to_peer(self) -> bool:
		"""Attempt to connect to peer lane"""
		if not self.config.peer_ip or not self.config.peer_port:
			logger.error("Peer connection details not configured")
			return False
			
		try:
			self.reader, self.writer = await asyncio.open_connection(
				self.config.peer_ip,
				self.config.peer_port
			)
			self.connected.set()
			logger.info(f"Connected to peer at {self.config.peer_ip}:{self.config.peer_port}")
			return True
		except Exception as e:
			logger.error(f"Failed to connect to peer: {e}")
			return False

	async def _handle_peer_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
		"""Handle incoming peer connection"""
		self.reader = reader
		self.writer = writer
		self.connected.set()
		addr = writer.get_extra_info('peername')
		logger.info(f"Peer connected from {addr}")
		
		try:
			while not self._shutdown.is_set():
				data = await reader.readline()
				if not data:
					break
					
				message = json.loads(data.decode())
				if self.data_callback:
					await self.data_callback(message)
					
		except Exception as e:
			logger.error(f"Error handling peer connection: {e}")
		finally:
			self.connected.clear()
			writer.close()
			await writer.wait_closed()

	async def send_data(self, data: Dict[str, Any]):
		"""Send data to peer lane"""
		if not self.connected.is_set():
			logger.error("No peer connection available")
			return False
			
		try:
			message = json.dumps(data).encode() + b'\n'
			self.writer.write(message)
			await self.writer.drain()
			return True
		except Exception as e:
			logger.error(f"Failed to send data to peer: {e}")
			return False

	async def handle_p2p_data(self, data):
		"""Handle data received from peer lane"""
		try:
			if data.get("type") == "frame_update":
				# Update local game state with peer data
				bowler_id = data["bowler_id"]
				frame_data = data["frame_data"]
				dispatcher.dispatch_event("update_peer_frame", {
					"bowler_id": bowler_id,
					"frame_data": frame_data
				})
		except Exception as e:
			logger.error(f"Error handling P2P data: {e}")

	async def start(self, data_callback):
		"""Start P2P connection handler"""
		self.data_callback = data_callback
		self.running = True
		
		# Start server
		server = await self.start_server()
		if not server:
			return False
			
		# If peer details are configured, try to connect
		if self.config.peer_ip and self.config.peer_port:
			await self.connect_to_peer()
			
		try:
			while not self._shutdown.is_set():
				if not self.connected.is_set():
					await asyncio.sleep(5)
					await self.connect_to_peer()
				await asyncio.sleep(1)
		except asyncio.CancelledError:
			pass
		finally:
			server.close()
			await server.wait_closed()
			self.running = False

	def stop(self):
		"""Stop P2P connection handler"""
		self._shutdown.set()
		if self.writer:
			self.writer.close()

class AsyncLaneClient:
	def __init__(self, lane_id=LaneID, host='172.20.10.2', port=50005):
		# Client configuration
		self.lane_id = str(lane_id)
		# Use known server IP if provided, otherwise use default
		self.host = host #or '192.168.2.243'  # Default to known server IP
		self.port = port
		self.HEADERSIZE = 10
		self.p2p_connection = None
		
		# Connection state
		self.message_queue = asyncio.Queue(maxsize=100)
		self.reader = None
		self.writer = None
		self.running = False
		self.registered = asyncio.Event()
		
		# Connection manager
		self.connection_manager = ConnectionManager()
		
		# Game state
		self.paired_lane = None
		self.game_started = False
		self.current_game_type = None
		self.current_players = []
		self.current_frame = 0
		self.bowler_stats = {}
		
		# Event loop
		self.loop = None
		self.tasks = []
		self._shutdown = asyncio.Event()

		logger.info(f"Initializing Async Lane Client {self.lane_id} connecting to {self.host}:{self.port}")
	
	async def start(self):
		"""Start with simplified connection logic"""
		logger.info(f"Attempting to connect to server at {self.host}:{self.port}")
		
		# Try direct connection without discovery
		return await self.register_with_server()

	async def run_client(self):
		"""Main client runner with simplified reconnection logic"""
		try:
			if not await self.start():
				logger.error("Failed to connect to server")
				# Retry logic with exponential backoff
				for i in range(5):  # Try up to 5 times
					wait_time = min(2 ** i, 30)  # Exponential backoff: 1, 2, 4, 8, 16, 30 seconds max
					logger.info(f"Retrying connection in {wait_time} seconds (attempt {i+1}/5)...")
					await asyncio.sleep(wait_time)
					if await self.start():
						logger.info("Successfully connected to server")
						break
				else:  # This runs if no break occurred in the loop
					logger.error("All connection attempts failed")
					return

			self.running = True
			
			# Create tasks
			self.tasks = [
				asyncio.create_task(self.heartbeat_loop(), name='heartbeat'),
				asyncio.create_task(self.listen_for_messages(), name='listener'),
				asyncio.create_task(self.monitor_tasks(), name='monitor'),
				asyncio.create_task(self.message_processor(), name='processor')
			]
			
			# Wait for shutdown signal
			await self._shutdown.wait()
			
			# Cancel all tasks
			for task in self.tasks:
				if not task.done():
					task.cancel()
			
			# Wait for all tasks to complete
			await asyncio.gather(*self.tasks, return_exceptions=True)
			
		except Exception as e:
			logger.error(f"Error in run_client: {e}")
		finally:
			self.running = False
	
	async def monitor_tasks(self):
		"""Monitor the status of our running tasks"""
		while self.running:
			try:
				current_tasks = asyncio.all_tasks()
				for task in current_tasks:
					if task.done() and not task.cancelled():
						exception = task.exception()
						if exception:
							logger.error(f"Task {task.get_name()} failed with: {exception}")
							# Consider restarting critical tasks
							if task.get_name() == 'heartbeat':
								logger.info("Restarting heartbeat task")
								self.tasks.append(asyncio.create_task(self.heartbeat_loop(), name='heartbeat'))
							elif task.get_name() == 'listener':
								logger.info("Restarting listener task")
								self.tasks.append(asyncio.create_task(self.listen_for_messages(), name='listener'))

				await asyncio.sleep(2)
			except Exception as e:
				logger.error(f"Monitor error: {e}")
				await asyncio.sleep(2)
	
	async def send_message(self, message):
		"""Send a message to the server."""
		try:
			if not self.writer:
				raise ConnectionError("No writer available to send message.")
	
			message_data = json.dumps(message).encode('utf-8') + b'\n'
			self.writer.write(message_data)
			await self.writer.drain()
		except Exception as e:
			logger.error(f"Error sending message: {e}")
			# Attempt reconnection on failure
			if not self.registered.is_set():
				if await self.reconnect_to_server():
					# Retry sending if reconnection succeeded
					try:
						message_data = json.dumps(message).encode('utf-8') + b'\n'
						self.writer.write(message_data)
						await self.writer.drain()
					except Exception as inner_e:
						logger.error(f"Failed to send message after reconnect: {inner_e}")

	async def register_with_server(self):
		try:
			logger.info(f"Attempting to connect to server at {self.host}:{self.port}")
			
			# Print network information for debugging
			try:
				local_ip = self.get_local_ip()
				logger.info(f"Client local IP: {local_ip}")
				logger.info(f"Client is running on lane_id: {self.lane_id}")
				
				# Try to check if server port is reachable using a socket
				sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
				sock.settimeout(2)
				result = sock.connect_ex((self.host, self.port))
				if result == 0:
					logger.info(f"Port {self.port} on {self.host} is OPEN and reachable")
				else:
					logger.error(f"Port {self.port} on {self.host} is NOT reachable (error code: {result})")
				sock.close()
			except Exception as net_e:
				logger.error(f"Network diagnostics error: {net_e}")
			
			# Try to establish connection with debug info
			try:
				logger.info("Opening connection...")
				connection_future = asyncio.open_connection(self.host, self.port)
				self.reader, self.writer = await asyncio.wait_for(connection_future, timeout=10.0)
				logger.info("Connection opened successfully")
			except asyncio.TimeoutError:
				logger.error("Connection timed out after 10 seconds")
				return False
			except ConnectionRefusedError:
				logger.error("Connection refused - server not running or firewall blocking")
				return False
			except Exception as conn_e:
				logger.error(f"Connection failed: {type(conn_e).__name__}: {conn_e}")
				return False
				
			logger.info("Connection established")
			
			if not self.reader or not self.writer:
				logger.error("Failed to establish reader and writer.")
				return False
			
			# Log connection details
			peer_name = self.writer.get_extra_info('peername')
			sock_name = self.writer.get_extra_info('sockname')
			logger.info(f"Connection details - Local: {sock_name}, Remote: {peer_name}")
			
			registration_data = {
				"type": "registration",
				"lane_id": self.lane_id,
				"listen_port": self.port,
				"client_ip": local_ip
			}
			
			logger.info(f"Sending registration data: {registration_data}")
			# Send registration data with newline
			message_data = json.dumps(registration_data).encode('utf-8') + b'\n'
			self.writer.write(message_data)
			await self.writer.drain()
			
			logger.info("Waiting for server response...")
			response_data = await asyncio.wait_for(self.reader.readline(), timeout=10.0)
			
			if not response_data:
				logger.error("Empty response from server")
				return False
				
			try:
				response = json.loads(response_data.decode('utf-8'))
				logger.info(f"Registration response: {response}")
				
				if response.get("status") == "success":
					logger.info(f"Lane {self.lane_id} successfully registered")
					self.registered.set()
					return True
				else:
					logger.warning(f"Unexpected server response: {response}")
					return False
			except json.JSONDecodeError as jde:
				logger.error(f"JSON decode error in registration response: {jde}")
				return False
				
		except asyncio.TimeoutError:
			logger.error("Timeout waiting for server response")
			return False
		except Exception as e:
			logger.error(f"Error during registration: {type(e).__name__}: {e}")
			return False
	
	async def message_processor(self):
		"""Dedicated message processor with better error handling"""
		while not self._shutdown.is_set():
			try:
				message = await self.message_queue.get()
				if not message:
					continue
					
				try:
					await self.process_message(message)
				except Exception as e:
					logger.error(f"Error processing message {message}: {e}")
					
				self.message_queue.task_done()
				
			except asyncio.CancelledError:
				break
			except Exception as e:
				logger.error(f"Message processor error: {e}")
				await asyncio.sleep(1)  # Prevent tight loop on errors
	
	async def heartbeat_loop(self):
		"""Improved heartbeat with better error handling and logging"""
		retry_count = 0
		max_retries = 5
		base_delay = 1
		max_delay = 30
		heartbeat_interval = 30  # Send heartbeat every 30 seconds
		
		logger.info("Starting heartbeat loop")
		
		while not self._shutdown.is_set():
			try:
				# If not registered, try to register
				if not self.registered.is_set():
					if retry_count >= max_retries:
						logger.info("Maximum registration retries reached, rediscovering server")
						self.host, self.port = await self.discover_server()
						retry_count = 0
					
					logger.info(f"Not registered, attempting to register (attempt {retry_count+1})")
					if not await self.register_with_server():
						retry_count += 1
						delay = min(base_delay * (2 ** retry_count), max_delay)
						logger.info(f"Registration failed, retrying in {delay} seconds")
						await asyncio.sleep(delay)
						continue
					else:
						logger.info("Registration successful")
						retry_count = 0
				
				# Send heartbeat if registered
				try:
					logger.debug("Sending heartbeat")
					await self.send_heartbeat()
					logger.debug("Heartbeat sent successfully")
					retry_count = 0  # Reset on success
				except Exception as he:
					logger.error(f"Error sending heartbeat: {he}")
					retry_count += 1
					
					# If we've had multiple heartbeat failures, try to reconnect
					if retry_count >= 3:
						logger.warning(f"Multiple heartbeat failures ({retry_count}), attempting to reconnect")
						self.registered.clear()  # Mark as not registered to trigger reconnection
						retry_count = 0
				
				# Wait for the next heartbeat interval
				await asyncio.sleep(heartbeat_interval)
				
			except asyncio.CancelledError:
				logger.info("Heartbeat loop cancelled")
				break
			except Exception as e:
				logger.error(f"Unexpected error in heartbeat loop: {e}")
				import traceback
				logger.error(f"Traceback: {traceback.format_exc()}")
				await asyncio.sleep(5)  # Brief delay before retrying
	
	async def check_connection(self):
		"""Check if the connection to the server is still good"""
		try:
			if not self.writer or self.writer.is_closing():
				logger.warning("Writer is closed or missing")
				return False
				
			# Try to send a heartbeat and wait for response
			heartbeat_message = {
				'type': 'heartbeat',
				'lane_id': self.lane_id,
				'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
			}
			
			# Send the heartbeat
			await self.send_message(heartbeat_message)
			
			# Wait for a response with timeout
			try:
				# Use a separate task for the read to allow timeout
				read_task = asyncio.create_task(self.reader.readline())
				response_data = await asyncio.wait_for(read_task, timeout=5.0)
				
				if not response_data:
					logger.warning("Empty response to heartbeat")
					return False
					
				response = json.loads(response_data.decode('utf-8'))
				
				# Check if it's a proper heartbeat response
				if response.get('type') == 'heartbeat_response':
					return True
					
				# If we got some other response, something's wrong
				logger.warning(f"Unexpected response to heartbeat: {response.get('type')}")
				return False
					
			except asyncio.TimeoutError:
				logger.warning("Heartbeat response timeout")
				return False
			except json.JSONDecodeError:
				logger.warning("Invalid JSON in heartbeat response")
				return False
		except Exception as e:
			logger.error(f"Error checking connection: {e}")
			return False
	
	async def reconnect_to_server(self):
		"""Improved reconnection logic with better error handling and backoff."""
		max_retries = 10
		retry_count = 0
		base_delay = 1
		max_delay = 30
		
		logger.info(f"Attempting to reconnect to server at {self.host}:{self.port}...")
		
		while retry_count < max_retries and not self._shutdown.is_set():
			try:
				# Close existing connection if any
				if self.writer:
					try:
						if not self.writer.is_closing():
							self.writer.close()
							await self.writer.wait_closed()
					except Exception as close_e:
						logger.warning(f"Error closing existing writer: {close_e}")
				
				# Before attempting reconnection, attempt to rediscover the server
				# This helps if the server has changed IP or port
				if retry_count > 2:  # Only try rediscovery after a few direct reconnection attempts
					logger.info("Attempting to rediscover server...")
					new_host, new_port = await self.discover_server()
					if new_host and new_port:
						if new_host != self.host or new_port != self.port:
							logger.info(f"Server rediscovered at new address: {new_host}:{new_port}")
							self.host = new_host
							self.port = new_port
				
				# Create new connection with timeout
				logger.info(f"Opening connection to {self.host}:{self.port}...")
				connect_task = asyncio.open_connection(self.host, self.port)
				self.reader, self.writer = await asyncio.wait_for(connect_task, timeout=10.0)
				
				logger.info("Reconnected to server, attempting registration")
				
				# Re-register
				registration_success = await self.register_with_server()
				if registration_success:
					logger.info("Successfully reconnected and registered with server")
					return True
				else:
					logger.warning("Reconnected but registration failed")
					retry_count += 1
			except asyncio.TimeoutError:
				logger.warning(f"Connection attempt timed out (attempt {retry_count+1}/{max_retries})")
				retry_count += 1
			except ConnectionRefusedError:
				logger.warning(f"Connection refused (attempt {retry_count+1}/{max_retries})")
				retry_count += 1
			except Exception as e:
				logger.error(f"Error during reconnection attempt {retry_count+1}: {e}")
				retry_count += 1
			
			# Calculate backoff delay
			delay = min(base_delay * (2 ** retry_count), max_delay)
			logger.info(f"Retrying connection in {delay} seconds...")
			await asyncio.sleep(delay)
		
		if retry_count >= max_retries:
			logger.error(f"Failed to reconnect after {max_retries} attempts")
		
		return False
	
	async def receive_message(self):
		"""Receive a message from the server with enhanced debugging"""
		try:
			if not self.reader:
				logger.warning("Receive_message called with no reader")
				return None
				
			logger.debug("Reading from server...")
			data = await self.reader.readline()
			
			if not data:
				logger.debug("Received empty data")
				return None
	
			# Log raw data
			logger.debug(f"Raw data received: {data[:50]}...")
			
			# Decode and parse
			message_str = data.decode('utf-8').strip()
			message = json.loads(message_str)
			logger.debug(f"Parsed message with type: {message.get('type')}")
			
			return message
			
		except asyncio.CancelledError:
			raise
		except json.JSONDecodeError as jde:
			logger.error(f"JSON decode error: {jde}")
			logger.error(f"Problematic data: {data.decode('utf-8', errors='replace')}")
			return None
		except Exception as e:
			logger.error(f"Error receiving message: {e}")
			return None

	async def send_heartbeat(self):
		"""Send a heartbeat message to the server with better error handling."""
		try:
			if not self.writer or self.writer.is_closing():
				logger.error("Cannot send heartbeat: Writer is None or closed")
				raise ConnectionError("Writer unavailable")
				
			message = {
				'type': 'heartbeat', 
				'lane_id': self.lane_id,
				'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
			}
			
			logger.debug(f"Sending heartbeat with timestamp: {message['timestamp']}")
			
			# Send the message
			await self.send_message(message)
			return True
		except Exception as e:
			logger.error(f"Error sending heartbeat: {e}")
			raise  # Re-raise to allow the heartbeat_loop to handle it
		
	async def process_message(self, data):
		"""Process incoming messages with standardized quick_game handling."""
		try:
			message_type = data.get('type')
			message_data = data.get('data')
			
			logger.info(f"Processing message of type: {message_type}")
			if message_data:
				logger.info(f"Message data sample: {json.dumps(message_data)[:100]}...")
			
			if message_type == "heartbeat_response":
				logger.debug(f"Received heartbeat response: {data}")
				return True
				
			if message_type == "ping":
				logger.info("Received ping, sending pong")
				pong_message = {
					'type': 'pong',
					'lane_id': self.lane_id,
					'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
				}
				await self.send_message(pong_message)
				return True
				
			if message_type == "heartbeat":
				logger.debug("Received heartbeat, ignoring.")
				return True
				
			# STANDARDIZED GAME HANDLING
			if message_type in ["quick_game", "league_game", "pre_bowl"]:
				logger.info(f"*** RECEIVED {message_type.upper()} ***")
				
				# Handle based on message type
				if message_type == "quick_game":
					await self.handle_quick_game(data)
				elif message_type == "league_game":
					# For league_game, the actual data might be inside the data field
					if message_data and isinstance(message_data, dict):
						await dispatcher.dispatch_event("league_game", message_data)
					else:
						await dispatcher.dispatch_event("league_game", data)
				elif message_type == "pre_bowl":
					await dispatcher.dispatch_event("pre_bowl", data)
				
				return True
			
			# Handle lane_command messages
			if message_type == "lane_command" and isinstance(message_data, dict):
				inner_type = message_data.get('type')
				logger.info(f"Received lane_command with inner type: {inner_type}")
				
				# For game commands, use their specific handlers
				if inner_type in ["quick_game", "league_game", "pre_bowl"]:
					logger.info(f"*** RECEIVED {inner_type.upper()} VIA LANE_COMMAND ***")
					
					# Create a standardized message format
					standardized_message = {
						'type': inner_type,
						'data': message_data
					}
					
					# Recursively process with the standardized format
					return await self.process_message(standardized_message)
				
				# For other command types
				if inner_type:
					logger.info(f"Dispatching {inner_type} event")
					await dispatcher.dispatch_event(inner_type, message_data)
					return True
			
			# For other message types, try to dispatch the event
			try:
				if message_type:
					logger.info(f"Dispatching generic event: {message_type}")
					await dispatcher.dispatch_event(message_type, message_data or data)
					return True
			except Exception as dispatch_e:
				logger.error(f"Error dispatching event {message_type}: {dispatch_e}")
			
			logger.warning(f"Unhandled message type: {message_type}")
			return False
			
		except Exception as e:
			logger.error(f"Error in process_message: {e}")
			import traceback
			logger.error(f"Traceback: {traceback.format_exc()}")
			return False

	async def handle_quick_game(self, data):
		"""Handle quick game command with increased logging."""
		try:
			logger.info(f"Received quick_game command with data: {json.dumps(data)[:200]}...")
			
			# Extract the game data - handle different message formats
			game_data = data
			
			# If data is a dict with type and data fields, extract the inner data
			if isinstance(data, dict) and 'type' in data and data.get('type') == 'quick_game' and 'data' in data:
				game_data = data.get('data')
				logger.info("Extracted inner game data from nested structure")
			
			# Check for double-nested structure and correct it
			if isinstance(game_data, dict) and 'type' in game_data and game_data.get('type') == 'quick_game':
				# Remove the redundant type field to prevent confusion
				game_data_copy = game_data.copy()
				game_data_copy.pop('type', None)
				game_data = game_data_copy
				logger.info("Removed redundant nested type field")
			
			# Simply dispatch the event to the BaseUI through the dispatcher
			logger.info(f"Dispatching quick_game event with data: {json.dumps(game_data)[:200]}...")
			await dispatcher.dispatch_event('quick_game', game_data)
			
			# Store game information
			self.game_started = True
			self.current_game_type = "quick_game"
			self.current_players = game_data.get('bowlers', [])
			
			logger.info("Quick game event dispatched successfully")
			return True
			
		except Exception as e:
			logger.error(f"Error handling quick_game command: {e}")
			import traceback
			logger.error(f"Traceback: {traceback.format_exc()}")
			return False

	async def handle_game_data_request(self, request_data):
		"""Handle a request for current game data"""
		try:
			# Prepare game data response
			game_data = self.collect_current_game_data()
			
			# Send response back to server
			response = {
				'type': 'game_data_response',
				'lane_id': self.lane_id,
				'data': game_data
			}
			
			await self.send_message(response)
			logger.info(f"Sent game data response for lane {self.lane_id}")
			
		except Exception as e:
			logger.error(f"Error handling game data request: {e}")
	
	def collect_current_game_data(self):
		"""Collect current game data from active game"""
		game_data = {
			'lane_id': self.lane_id,
			'current_game_type': self.current_game_type,
		}
		
		# Get data from current game
		if hasattr(self, 'quick_game') and self.quick_game:
			# It's a quick game
			game_data['type'] = 'quick_game'
			game_data['current_game'] = getattr(self.quick_game, 'current_game_number', 1)
			game_data['total_games'] = getattr(self.quick_game.settings, 'total_games', 1)
			
			# Collect bowler data
			bowlers_data = []
			for bowler in getattr(self.quick_game, 'bowlers', []):
				bowler_data = {
					'name': bowler.name,
					'frames': [],
					'total_score': bowler.total_score,
					'current_frame': bowler.current_frame
				}
				
				# Collect frame data
				for frame in bowler.frames:
					frame_data = {
						'balls': [],
						'total': frame.total,
						'is_strike': frame.is_strike,
						'is_spare': frame.is_spare
					}
					
					# Collect ball data
					for ball in frame.balls:
						ball_data = {
							'value': ball.value,
							'symbol': ball.symbol,
							'pin_config': ball.pin_config
						}
						frame_data['balls'].append(ball_data)
					
					bowler_data['frames'].append(frame_data)
				
				bowlers_data.append(bowler_data)
			
			game_data['bowlers'] = bowlers_data
			
		elif hasattr(self, 'league_game') and self.league_game:
			# It's a league game
			game_data['type'] = 'league_game'
			game_data['current_game'] = getattr(self.league_game, 'current_game_number', 1)
			game_data['total_games'] = getattr(self.league_game.settings, 'total_games', 1)
			game_data['paired_lane'] = getattr(self.league_game, 'paired_lane', None)
			
			# Collect bowler data similar to quick game
			# [Same code as for quick game]
			
		elif hasattr(self, 'hangman_game') and self.hangman_game:
			# It's a hangman game
			game_data['type'] = 'hangman'
			game_data['players'] = [{'name': b.name} for b in self.hangman_game.bowlers]
			game_data['hangman_states'] = self.hangman_game.hangman_states
		
		return game_data
			
	async def discover_server(self):
		"""Discover server using multiple methods"""
		# Try multicast discovery first
		result = await self._discover_via_multicast()
		if result[0]:
			return result
			
		# If multicast fails, try subnet scanning
		result = await self._discover_via_subnet_scan()
		if result[0]:
			return result
			
		# If all else fails, return None
		return None, None
				
	async def _discover_via_multicast(self):
		"""Discover server using multicast"""
		multicast_group = '224.3.29.71'
		multicast_port = 50005
		message = b'LANE_DISCOVERY_REQUEST'
		
		sock = None
		
		logger.info("Attempting server discovery via multicast...")
		
		try:
			# Create UDP socket for multicast
			sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
			sock.settimeout(5.0)  # Increased timeout to 5 seconds
			ttl = struct.pack('b', 2)  # Increased TTL to 2 for better network reach
			sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)
			
			# Try multiple times
			for attempt in range(3):
				# Send discovery request
				logger.info(f"Sending discovery request to {multicast_group}:{multicast_port} (attempt {attempt+1}/3)")
				sock.sendto(message, (multicast_group, multicast_port))
				
				# Listen for responses with timeout
				start_time = time.time()
				while time.time() - start_time < 8:  # Increased to 8 seconds
					try:
						data, server = sock.recvfrom(1024)
						logger.info(f"Received response from {server}")
						if data.startswith(b'LANE_DISCOVERY_RESPONSE'):
							try:
								response_data = data[24:].decode()
								logger.debug(f"Response data: {response_data}")
								response = json.loads(response_data)
								if response.get('type') == 'server_info':
									host = response.get('host')
									port = response.get('port', 50005)
									if host:
										logger.info(f"Server discovered at {host}:{port}")
										return host, port
							except json.JSONDecodeError as je:
								logger.warning(f"Invalid JSON in discovery response: {je}")
								logger.debug(f"Raw response data: {data[24:]}")
								continue
					except socket.timeout:
						continue
				
				# If we've waited the full time without a response, try again
				logger.info(f"No response received on attempt {attempt+1}")
				await asyncio.sleep(0.5)  # Small delay between attempts
			
			logger.warning("Multicast discovery failed after 3 attempts")
			return None, None
		except Exception as e:
			logger.error(f"Multicast discovery error: {e}")
			return None, None
		finally:
			if sock:
				sock.close()
	
	async def _discover_via_subnet_scan(self):
		"""Scan local subnet for server"""
		logger.info("Attempting server discovery via subnet scan...")
		
		# Get local IP to determine subnet
		local_ip = self.get_local_ip()
		if local_ip == '127.0.0.1':
			logger.warning("Could not determine local IP, using default subnet")
			subnet_base = "192.168.1."
		else:
			# Extract subnet from local IP
			subnet_parts = local_ip.split('.')
			subnet_base = f"{subnet_parts[0]}.{subnet_parts[1]}.{subnet_parts[2]}."
		
		logger.info(f"Scanning subnet: {subnet_base}*")
		
		# Common server ports to check
		server_port = 50005
		
		# List of IPs to try (common server IPs first)
		potential_ips = [
			f"{subnet_base}1",   # Default gateway 
			f"{subnet_base}100", # Common server address
			f"{subnet_base}254", # Another common server address
			f"{subnet_base}243", # The address you've been using
			"192.168.2.243",	# Hardcoded previous address
			"192.168.58.103"	# Another hardcoded address from your code
		]
		
		# Add some common device IPs in the subnet
		for i in range(2, 20):
			ip = f"{subnet_base}{i}"
			if ip not in potential_ips:
				potential_ips.append(ip)
		
		# Try connection to each IP
		for ip in potential_ips:
			try:
				logger.info(f"Trying to connect to {ip}:{server_port}")
				reader, writer = await asyncio.wait_for(
					asyncio.open_connection(ip, server_port),
					timeout=1.0
				)
				
				# If we can connect, try registering
				logger.info(f"Connected to {ip}:{server_port}, testing if it's a lane server")
				
				# Close the test connection
				writer.close()
				await writer.wait_closed()
				
				# Return the IP for actual registration
				return ip, server_port
				
			except (asyncio.TimeoutError, ConnectionRefusedError):
				# Expected for non-server IPs, continue silently
				pass
			except Exception as e:
				logger.debug(f"Error scanning {ip}: {e}")
		
		logger.warning("Subnet scan completed, no server found")
		return None, None

	def get_local_ip(self):
		"""Get local IP address"""
		try:
			s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
			s.connect(('8.8.8.8', 80))
			ip = s.getsockname()[0]
			s.close()
			return ip
		except:
			return '127.0.0.1'

	def stop(self):
		"""Stop the client and cancel tasks."""
		if self.running:
			logger.info("Stopping client and canceling tasks.")
		else:
			logger.warning("Client already stopped.")
		self.running = False
		self._shutdown.set()

	def run(self):
		"""Run the client"""
		self.loop = asyncio.new_event_loop()
		asyncio.set_event_loop(self.loop)
		
		try:
			self.loop.run_until_complete(self.run_client())
		except KeyboardInterrupt:
			logger.info("Keyboard interrupt received")
		finally:
			self.cleanup()

	def cleanup(self):
		"""Clean up resources"""
		logger.info("Starting cleanup")
		
		self.connection_manager.close_all()
		
		# Signal tasks to shut down
		if not self._shutdown.is_set():
			self.loop.call_soon_threadsafe(self._shutdown.set)
		
		# Close the writer if it exists
		if hasattr(self, 'writer') and self.writer and not self.writer.is_closing():
			self.writer.close()
		
		# Close the loop
		if self.loop:
			try:
				# Cancel any remaining tasks
				remaining_tasks = asyncio.all_tasks(self.loop)
				for task in remaining_tasks:
					task.cancel()
				
				# Wait for tasks to complete
				if remaining_tasks:
					self.loop.run_until_complete(
						asyncio.gather(*remaining_tasks, return_exceptions=True)
					)
			finally:
				self.loop.close()
		
		logger.info("Cleanup completed")
		
	async def run_diagnostics(self):
		"""Run a complete diagnostic check on the client and connection"""
		try:
			# Record the start time
			start_time = time.time()
			diagnostics = {
				"timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
				"lane_id": self.lane_id,
				"network": {},
				"connection": {},
				"game_state": {},
				"event_system": {}
			}
			
			# 1. Network Diagnostics
			logger.info("Running network diagnostics...")
			local_ip = self.get_local_ip()
			diagnostics["network"]["local_ip"] = local_ip
			diagnostics["network"]["server_ip"] = self.host
			diagnostics["network"]["server_port"] = self.port
			
			# Ping the server IP to check basic connectivity
			ping_result = await self._ping_host(self.host)
			diagnostics["network"]["ping_server"] = ping_result
			
			# 2. Connection Diagnostics
			logger.info("Running connection diagnostics...")
			diagnostics["connection"]["registered"] = self.registered.is_set()
			diagnostics["connection"]["writer_available"] = self.writer is not None
			diagnostics["connection"]["writer_closing"] = self.writer.is_closing() if self.writer else True
			
			# Test the connection with a ping message
			if self.writer and not self.writer.is_closing():
				connection_good = await self.check_connection()
				diagnostics["connection"]["ping_test"] = connection_good
			else:
				diagnostics["connection"]["ping_test"] = False
			
			# 3. Game State Diagnostics
			logger.info("Running game state diagnostics...")
			diagnostics["game_state"]["game_started"] = getattr(self, 'game_started', False)
			diagnostics["game_state"]["current_game_type"] = self.current_game_type
			diagnostics["game_state"]["current_players"] = len(self.current_players)
			
			# Check if we have a quick_game or league_game instance
			has_quick_game = hasattr(self, 'quick_game') and self.quick_game is not None
			has_league_game = hasattr(self, 'league_game') and self.league_game is not None
			diagnostics["game_state"]["has_quick_game"] = has_quick_game
			diagnostics["game_state"]["has_league_game"] = has_league_game
			
			# 4. Event System Diagnostics
			logger.info("Running event system diagnostics...")
			if hasattr(dispatcher, 'listeners'):
				# Count listeners for each event type
				event_listeners = {}
				for event_type, handlers in dispatcher.listeners.items():
					event_listeners[event_type] = len(handlers)
				diagnostics["event_system"]["listeners"] = event_listeners
			
			# Calculate total time
			diagnostics["total_time"] = f"{time.time() - start_time:.2f} seconds"
			
			# Log diagnostics
			logger.info(f"Diagnostics complete: {json.dumps(diagnostics, indent=2)}")
			
			# Return diagnostics data
			return diagnostics
			
		except Exception as e:
			logger.error(f"Error running diagnostics: {e}")
			import traceback
			logger.error(f"Traceback: {traceback.format_exc()}")
			return {"error": str(e)}
	
	async def _ping_host(self, host, count=3, timeout=1.0):
		"""Ping a host to check connectivity"""
		try:
			# Create socket for a simple connection test
			sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
			sock.settimeout(timeout)
			
			# Wrap in asyncio to not block
			def _do_ping():
				try:
					sock.connect((host, self.port))
					sock.close()
					return True
				except Exception:
					return False
			
			# Run in a separate thread
			result = await asyncio.get_event_loop().run_in_executor(None, _do_ping)
			return result
		except Exception as e:
			logger.error(f"Error pinging host: {e}")
			return False
	
	async def send_diagnostics_to_server(self):
		"""Run diagnostics and send results to server"""
		try:
			# Run diagnostics
			diagnostics = await self.run_diagnostics()
			
			# Prepare diagnostic message
			message = {
				'type': 'lane_diagnostics',
				'lane_id': self.lane_id,
				'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
				'data': diagnostics
			}
			
			# Send to server
			await self.send_message(message)
			logger.info("Sent diagnostics to server")
			return True
		except Exception as e:
			logger.error(f"Error sending diagnostics: {e}")
			return False
	
	async def listen_for_messages(self):
		"""Enhanced message listener with proper timeouts"""
		reconnection_attempts = 0
		max_reconnection_attempts = 10
		
		while not self._shutdown.is_set():
			try:
				if not self.reader:
					logger.warning("No reader available, waiting...")
					await asyncio.sleep(1)
					continue
					
				logger.debug("Waiting for incoming message...")
				
				# Add timeout to read operation - increased to 90 seconds
				try:
					read_task = asyncio.create_task(self.reader.readline())
					data = await asyncio.wait_for(read_task, timeout=90.0)  # Match server's heartbeat timeout
					
					# Reset reconnection attempts on successful read
					reconnection_attempts = 0
					
					if data:
						# Process the data as before
						logger.debug(f"Raw data received ({len(data)} bytes): {data[:50]}...")
						
						try:
							message_str = data.decode('utf-8').strip()
							message = json.loads(message_str)
							
							# Put message in processing queue
							await self.message_queue.put(message)
						except json.JSONDecodeError as jde:
							logger.error(f"JSON decode error: {jde}")
						except Exception as parse_e:
							logger.error(f"Error parsing message: {parse_e}")
					else:
						# Empty data means the connection was closed
						logger.warning("Received empty data - connection may be closed")
						raise ConnectionError("Connection closed by server (empty read)")
						
				except asyncio.TimeoutError:
					# Timeout on read could mean server is unresponsive
					logger.debug("Read timeout - normal if no messages")
					continue
					
			except ConnectionError as ce:
				logger.warning(f"Connection error: {ce}")
				
				# Mark as not registered to trigger reconnection
				self.registered.clear()
				
				reconnection_attempts += 1
				if reconnection_attempts > max_reconnection_attempts:
					logger.error(f"Exceeded maximum reconnection attempts ({max_reconnection_attempts})")
					await asyncio.sleep(60)  # Long delay before retrying again
					reconnection_attempts = 0
				else:
					# Try to reconnect
					logger.info(f"Attempting reconnection ({reconnection_attempts}/{max_reconnection_attempts})...")
					if await self.reconnect_to_server():
						logger.info("Reconnection successful")
						reconnection_attempts = 0
					else:
						logger.warning("Reconnection failed")
						await asyncio.sleep(reconnection_attempts * 2)  # Increasing delay between attempts
			except asyncio.CancelledError:
				logger.info("Message listener cancelled")
				break
			except Exception as e:
				logger.error(f"Listener error: {e}")
				import traceback
				logger.error(f"Traceback: {traceback.format_exc()}")
				await asyncio.sleep(1)

# Rest of the code remains the same
class ConnectionManager:
	def __init__(self):
		self.connections = {}
		self.lock = asyncio.Lock()
		self.connection_timeouts = {}  # Track connection attempts
		
	async def close_all(self):
		async with self.lock:
			for key, conn in self.connections.items():
				writer = conn['writer']
				if not writer.is_closing():
					writer.close()
					await writer.wait_closed()
			self.connections.clear()


if __name__ == "__main__":
	logging.basicConfig(
		level=logging.DEBUG,
		format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
	)
	
	client = AsyncLaneClient()
	try:
		client.run()
	except KeyboardInterrupt:
		logger.info("Main thread received keyboard interrupt")
		client.cleanup()