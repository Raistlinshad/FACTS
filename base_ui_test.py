# -*- coding: utf-8 -*-
"""
Created on Fri Feb 21 14:35:11 2025

@author: AlexFogarty
"""

# base_ui.py
import tkinter as tk
import asyncio
from datetime import datetime
from threading import Thread, Lock
import time
import os
import json
import logging
from games1 import QuickGame, LeagueGame, GameSettings, setup_logging, PracticeGame
import RPi.GPIO as GPIO
import busio
import board
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn as AIN
import subprocess
import sys
from event_dispatcher import dispatcher
from Lane_Client_2 import AsyncLaneClient as AsyncClient

control = [0,0,0,0,0]

# Load settings
with open('settings.json') as f:
	lane_settings = json.load(f)
	
LaneID = lane_settings["Lane"]
print("Lane ID: ", LaneID)
logger = setup_logging()
mp = 0 

class SystemControlWindow:
	def __init__(self, parent=None):
		self.parent = parent
		self.window = tk.Toplevel(parent) if parent else tk.Tk()
		self.window.title("System Control")
		self.window.geometry("400x300")
		self.window.configure(bg="black")
		
		# Make window modal and always on top
		self.window.transient(parent)
		self.window.grab_set()
		self.window.focus_set()
		
		# Center the window
		self.center_window()
		
		# Create main frame
		main_frame = tk.Frame(self.window, bg="black")
		main_frame.pack(expand=True, fill="both", padx=20, pady=20)
		
		# Title
		title_label = tk.Label(main_frame, text="System Control", 
							  bg="black", fg="white", 
							  font=("Arial", 24, "bold"))
		title_label.pack(pady=(0, 30))
		
		# Button style
		button_style = {
			"width": 25,
			"height": 2,
			"font": ("Arial", 14),
			"relief": "raised",
			"bd": 3
		}
		
		# System control buttons
		tk.Button(main_frame, text="Exit to Desktop", 
				 command=self.exit_to_desktop, 
				 bg="green", fg="white",
				 **button_style).pack(pady=8)
		
		tk.Button(main_frame, text="Restart Application", 
				 command=self.restart_app, 
				 bg="blue", fg="white",
				 **button_style).pack(pady=8)
		
		tk.Button(main_frame, text="Restart to Desktop Mode", 
				 command=self.restart_to_desktop, 
				 bg="orange", fg="white",
				 **button_style).pack(pady=8)
		
		tk.Button(main_frame, text="Shutdown System", 
				 command=self.shutdown_system, 
				 bg="red", fg="white",
				 **button_style).pack(pady=8)
		
		tk.Button(main_frame, text="Cancel", 
				 command=self.close_window, 
				 bg="gray", fg="white",
				 **button_style).pack(pady=(20, 0))

	def center_window(self):
		"""Center the window on screen"""
		self.window.update_idletasks()
		width = self.window.winfo_width()
		height = self.window.winfo_height()
		x = (self.window.winfo_screenwidth() // 2) - (width // 2)
		y = (self.window.winfo_screenheight() // 2) - (height // 2)
		self.window.geometry(f'{width}x{height}+{x}+{y}')

	def exit_to_desktop(self):
		"""Exit application and return to desktop"""
		if tk.messagebox.askyesno("Confirm Exit", 
							  "Exit bowling application and return to desktop?\n\n" +
							  "The application will not restart automatically."):
			try:
				# Disable autostart by renaming the file
				autostart_file = os.path.expanduser("~/.config/autostart/bowling.desktop")
				if os.path.exists(autostart_file):
					os.rename(autostart_file, autostart_file + ".disabled")
					logger.info("Autostart disabled")
				
				# Cleanup and exit
				if self.parent and hasattr(self.parent, 'cleanup'):
					self.parent.cleanup()
				
				# Force exit
				os._exit(0)
				
			except Exception as e:
				logger.error(f"Error during exit to desktop: {e}")
				os._exit(1)

	def restart_app(self):
		"""Restart the bowling application"""
		if tk.messagebox.askyesno("Confirm Restart", 
							  "Restart the bowling application?\n\n" +
							  "All current game data will be lost."):
			try:
				# Cleanup current instance
				if self.parent and hasattr(self.parent, 'cleanup'):
					self.parent.cleanup()
				
				# Restart the application
				python = sys.executable
				os.execl(python, python, *sys.argv)
				
			except Exception as e:
				logger.error(f"Error during application restart: {e}")
				tk.messagebox.showerror("Restart Failed", f"Could not restart application: {e}")

	def restart_to_desktop(self):
		"""Restart system but disable autostart so it boots to desktop"""
		if tk.messagebox.askyesno("Confirm System Restart", 
							  "Restart system to desktop mode?\n\n" +
							  "The bowling application will not start automatically.\n" +
							  "You can re-enable it later from the desktop."):
			try:
				# Disable autostart
				autostart_file = os.path.expanduser("~/.config/autostart/bowling.desktop")
				if os.path.exists(autostart_file):
					os.rename(autostart_file, autostart_file + ".disabled")
					logger.info("Autostart disabled for desktop boot")
				
				# Cleanup
				if self.parent and hasattr(self.parent, 'cleanup'):
					self.parent.cleanup()
				
				# Restart system
				subprocess.run(["sudo", "reboot"], check=True)
				
			except subprocess.CalledProcessError as e:
				logger.error(f"Failed to restart system: {e}")
				tk.messagebox.showerror("Restart Failed", 
								   "Could not restart system. Check sudo permissions.")
			except Exception as e:
				logger.error(f"Error during system restart: {e}")
				tk.messagebox.showerror("Error", f"Error during restart: {e}")

	def shutdown_system(self):
		"""Shutdown the system"""
		if tk.messagebox.askyesno("Confirm Shutdown", 
							  "Shutdown the system?\n\n" +
							  "This will turn off the bowling system completely."):
			try:
				# Cleanup
				if self.parent and hasattr(self.parent, 'cleanup'):
					self.parent.cleanup()
				
				# Shutdown system
				subprocess.run(["sudo", "shutdown", "now"], check=True)
				
			except subprocess.CalledProcessError as e:
				logger.error(f"Failed to shutdown system: {e}")
				tk.messagebox.showerror("Shutdown Failed", 
								   "Could not shutdown system. Check sudo permissions.")
			except Exception as e:
				logger.error(f"Error during shutdown: {e}")
				tk.messagebox.showerror("Error", f"Error during shutdown: {e}")

	def close_window(self):
		"""Close the system control window"""
		self.window.destroy()

class BaseUI(tk.Tk):
	def __init__(self, lane_id):
		# Ensure only one root window exists
		existing_root = tk._default_root
		if existing_root is not None and existing_root != self:
			logger.warning("Another Tkinter root window exists - destroying it")
			existing_root.destroy()
		
		super().__init__()
		
		# initialization guard
		if hasattr(self, '_initialized'):
			logger.warning("BaseUI already initialized, skipping duplicate initialization")
			return
		
		self._initialized = True
		
		self.lane_id = lane_id
		self.title(f"Lane {self.lane_id}")
		self.geometry('1500x750')
		self.after(250, self.wm_attributes, '-fullscreen', 'true')
		self.configure(bg="blue")
		
		# Create the machine instance once
		self.machine = MachineFunctions()
		
		# Initialize event listeners
		self.setup_event_listeners()
	
		# Top Bar
		self.top_bar = tk.Frame(self, bg="black", height=50)
		self.top_bar.pack(fill=tk.X)
	
		# Use grid layout for the top bar
		self.top_bar.grid_columnconfigure(0, weight=1)  # Lane number
		self.top_bar.grid_columnconfigure(1, weight=2)  # Game display
		self.top_bar.grid_columnconfigure(2, weight=1)  # Date, time, and additional info
	
		# Left Side: Lane Number
		self.lane_label = tk.Label(self.top_bar, text=f"Lane {self.lane_id}", bg="black", fg="white", font=("Arial", 20))
		self.lane_label.grid(row=0, column=0, sticky="w", padx=10)
	
		# Middle: Current Bowler or Game Type
		self.game_display = tk.Label(self.top_bar, text="No Game Active", bg="black", fg="white", font=("Arial", 20))
		self.game_display.grid(row=0, column=1, sticky="ew", padx=10)
	
		# Right: Date and Time
		self.date_time_label = tk.Label(self.top_bar, text=self.get_current_time(), bg="black", fg="white", font=("Arial", 20))
		self.date_time_label.grid(row=0, column=2, sticky="e", padx=10)
	
		# Right (below date and time): Additional Information
		self.info_label = tk.Label(self.top_bar, text="Games Remaining: 0", bg="black", fg="white", font=("Arial", 16))
		self.info_label.grid(row=1, column=2, sticky="e", padx=10)
		
		# Main information window
		self.game_window = tk.Frame(self , bg='black')
		self.game_window.pack(fill=tk.BOTH)
	
		# Bottom Bar: Scrolling Text
		self.bottom_bar = tk.Frame(self, bg="black", height=30)
		self.bottom_bar.pack(fill=tk.X, side=tk.BOTTOM)
	
		self.scroll_text = tk.Label(self.bottom_bar, text="", bg="black", fg="white", font=("Arial", 16))
		self.scroll_text.pack()
	
		# Initialize scrolling variables
		self.scroll_message = ""
		self.scroll_position = 0
		
		# Day first boot options
		self.setup_system_menu()
		self.add_system_button()
		
		# Setup Client
		self.setup_client()
		
		# Start the clock and scrolling text updates using after() instead of threads
		self.after(100, self.update_clock)
		self.after(100, self.update_scroll_text)
		
		# State for ball detector when called
		self.ball_detector = None

	def add_system_button(self):
		"""Add a system button to the top bar for easy access"""
		# Add system button to the right side of top bar
		self.system_button = tk.Button(self.top_bar, 
									  text="⚙️ System", 
									  command=self.open_system_controls,
									  bg="darkred", fg="white", 
									  font=("Arial", 12),
									  relief="raised", bd=2)
		self.system_button.grid(row=0, column=3, sticky="e", padx=5)
		
		# Adjust column configuration to accommodate the new button
		self.top_bar.grid_columnconfigure(3, weight=0)
		
	def setup_client(self):
		# Always create a fresh client
		logger.info("Creating fresh client connection")
		self.client = AsyncClient()
		
		# Ensure clean shutdown
		self.protocol("WM_DELETE_WINDOW", self.cleanup)
		
		# Start client in a dedicated thread
		self.client_thread = Thread(target=self.run_client, daemon=True)
		self.client_thread.start()
	
	def send_to_lane(self, target_lane, message_type, data):
		"""Send a message to another lane via the client."""
		try:
			if hasattr(self, 'client') and self.client:
				# Create the message in the expected format
				message = {
					'type': 'lane_command',
					'lane_id': target_lane,
					'data': data
				}
				
				# Send via client - need to handle asyncio properly
				import asyncio
				
				# Create a task to send the message
				def send_async():
					loop = asyncio.new_event_loop()
					asyncio.set_event_loop(loop)
					try:
						loop.run_until_complete(self.client.send_message(message))
						logger.info(f"Successfully sent {message_type} to lane {target_lane}")
					except Exception as e:
						logger.error(f"Error sending message to lane {target_lane}: {e}")
					finally:
						loop.close()
				
				# Run in a separate thread to avoid blocking
				from threading import Thread
				send_thread = Thread(target=send_async, daemon=True)
				send_thread.start()
				
				return True
			else:
				logger.error("No client available to send message")
				return False
				
		except Exception as e:
			logger.error(f"Error in send_to_lane: {e}")
			return False

	def run_client(self):
		"""Run the AsyncLaneClient in its own event loop."""
		loop = asyncio.new_event_loop()
		asyncio.set_event_loop(loop)
		try:
			loop.run_until_complete(self.client.run_client())
			#loop.run_forever()
		except Exception as e:
			logger.error(f"Error in run_client: {e}")
		finally:
			loop.close()
		
	def setup_event_listeners(self):
		"""Register event listeners with proper error handling"""
		logger.info("Setting up event listeners...")
		
		logger.info("Registered listener for 'quick_game'")
		handlers = {
			'quick_game': self.start_quick_game,
			'league_game': self.start_league_game,
			'skip_pressed': self.activate_ball_detector,
			'set_game_display': self.set_game_display,
			'pin_set': self.handle_pin_set,
			'test_message': self.handle_test_message,
			'scroll_message': self.set_scroll_message,
			'force_full_reset': self.handle_force_full_reset,
			'bowler_move': self.handle_bowler_move,
			'frame_update': self.handle_frame_update,
			'game_complete': self.handle_game_complete,
			'request_machine_status': self.handle_request_machine_status,
			'schedule_reset': self.handle_schedule_reset,
			'schedule_pin_restore': self.handle_schedule_pin_restore,
			'end_game_request': self.handle_end_game_request,
			'practice_game': self.handle_start_practice_game
		}
		
		for event, handler in handlers.items():
			try:
				dispatcher.register_listener(event, handler)
				logger.info(f"Registered event handler for {event}")
			except Exception as e:
				logger.error(f"Failed to register handler for {event}: {e}")
				
	def setup_system_menu(self):
		"""Add system control menu to the main window"""
		# Create menu bar if it doesn't exist
		if not hasattr(self, 'menubar'):
			self.menubar = tk.Menu(self)
			self.config(menu=self.menubar)
		
		# Add system menu
		system_menu = tk.Menu(self.menubar, tearoff=0, bg="black", fg="white")
		self.menubar.add_cascade(label="System", menu=system_menu)
		
		system_menu.add_command(label="System Controls", command=self.open_system_controls)
		system_menu.add_separator()
		system_menu.add_command(label="Re-enable Autostart", command=self.enable_autostart)
	
	def open_system_controls(self):
		"""Open the system control window"""
		try:
			SystemControlWindow(self)
		except Exception as e:
			logger.error(f"Error opening system controls: {e}")
			tk.messagebox.showerror("Error", f"Could not open system controls: {e}")
	
	def enable_autostart(self):
		"""Re-enable autostart if it was disabled"""
		try:
			autostart_file = os.path.expanduser("~/.config/autostart/bowling.desktop")
			disabled_file = autostart_file + ".disabled"
			
			if os.path.exists(disabled_file):
				os.rename(disabled_file, autostart_file)
				tk.messagebox.showinfo("Autostart Enabled", 
								   "Autostart has been re-enabled.\n" +
								   "The bowling application will start automatically on next boot.")
				logger.info("Autostart re-enabled")
			else:
				tk.messagebox.showinfo("Autostart Status", 
								   "Autostart is already enabled or the disabled file was not found.")
		except Exception as e:
			logger.error(f"Error enabling autostart: {e}")
			tk.messagebox.showerror("Error", f"Could not enable autostart: {e}")

	def get_current_time(self):
		return datetime.now().strftime("%Y/%m/%d %H:%M")
		
	def handle_pin_set(self, data=None):
		"""Handle the pin_set event by updating MachineFunctions control state."""
		if not data:
			logger.error("No data provided to handle_pin_set")
			return

		logger.info(f"Updating machine control with pin set data: {data}")
		
		# Update the control dictionary with the new pin states
		for pin_name, state in data.items():
			if pin_name in self.machine.control:
				self.machine.control[pin_name] = state
		
		logger.info(f"Updated machine control state: {self.machine.control}")
		
		# Now restore pins with the updated control state
		self.machine.pin_restore(data)
		
	def handle_schedule_reset(self, data=None):
		reset_type = data.get('type', 'FULL_RESET') if data else 'FULL_RESET'
		immediate = data.get('immediate', False) if data else False
		
		logger.info(f"Handling schedule_reset event: {reset_type}, immediate: {immediate}")
		
		if hasattr(self, 'machine'):
			if immediate and reset_type == 'FULL_RESET':
				# For immediate full resets, set the force flag and call reset directly
				logger.info("IMMEDIATE_FULL_RESET: Setting force flag and resetting")
				self.machine._force_full_reset = True
				self.machine.reset_pins()
			else:
				# Use normal scheduling
				self.machine.schedule_reset(reset_type, data)
		else:
			logger.error("No machine available for scheduled reset")
	
	def handle_force_full_reset(self, data=None):
		logger.info("Handling force_full_reset event...")
		if hasattr(self, 'machine'):
			# Set force flag and reset immediately
			self.machine._force_full_reset = True
			self.machine.reset_pins()
		else:
			logger.error("No machine available for force full reset")
		
	# TODO: Remove this after testing
	async def handle_test_message(self, data):
		"""Handle test messages sent from the UI"""
		try:
			await self.client.process_message(data)
			self.after(0)
		except Exception as e:
			error_msg = f"Test failed: {str(e)}"
			logger.error(error_msg)
			self.after(0)
	
	def handle_schedule_pin_restore(self, data=None):
		"""Handle scheduled pin restore requests"""
		logger.info(f"Handling schedule_pin_restore event: {data}")
		
		if hasattr(self, 'machine'):
			self.machine.schedule_pin_restore(data)
		else:
			logger.error("No machine available for scheduled pin restore")
			
	def run_dispatch(self, test_data):
		"""Run the dispatch in a separate thread with its own event loop"""
		loop = asyncio.new_event_loop()
		asyncio.set_event_loop(loop)
		try:
			loop.run_until_complete(dispatcher.dispatch_event('test_message', test_data))
			self.after(0, lambda: self.set_scroll_message("Test successful"))
		except Exception as e:
			error_msg = f"Test failed: {str(e)}"
			logger.error(error_msg)
			self.after(0, lambda: self.set_scroll_message(error_msg))
		finally:
			loop.close()

	def activate_ball_detector(self, data=None):
		"""Activate the ball detector when skip is pressed."""
		logger.info("Activating ball detector...")
		
		pass
		'''
		if self.ball_detector == None:
			pass
		else:
			self.ball_detector.set_suspended(False)
		'''
		
	def update_clock(self):
		try:
			self.date_time_label.config(text=self.get_current_time())
			# Schedule next update
			self.after(1000, self.update_clock)
		except Exception as e:
			logger.info(f"Error updating clock: {e}")
	
	def update_scroll_text(self):
		try:
			if self.scroll_message:
				# Move the scroll position
				self.scroll_position = (self.scroll_position + 1) % (len(self.scroll_message) + 20)
				display_text = self.scroll_message[self.scroll_position:] + " " + self.scroll_message[:self.scroll_position]
				self.scroll_text.config(text=display_text)
			# Always continue the cycle
			self.after(200, self.update_scroll_text)
		except Exception as e:
			logger.info(f"Error updating scroll text: {e}")
			
	def update_lane_status(self, status):
		"""Update the lane status on the server"""
		try:
			if hasattr(self, 'client'):
				message = {
					'type': 'status_update',
					'lane_id': self.lane_id,
					'status': status
				}
				# Queue the message to be sent
				if hasattr(self.client, 'send_message'):
					asyncio.create_task(self.client.send_message(message))
				logger.info(f"Lane {self.lane_id} status updated to {status}")
		except Exception as e:
			logger.error(f"Error updating lane status: {e}")

	def set_game_display(self, text):
		self.game_display.config(text=text)

	def set_info_label(self, text):
		"""Set the info label text in the top bar."""
		if hasattr(self, 'info_label') and self.info_label:
			self.info_label.config(text=text)
		else:
			logger.warning(f"Info label not available to set text: {text}")
			
	def set_scroll_message(self, message):
		"""Set the scrolling message, handling newlines properly."""
		if hasattr(self, 'scroll_text') and self.scroll_text:
			# Replace \n with spaces for single line display
			display_message = message.replace('\n', ' ')
			self.scroll_text.config(text=display_message)
			logger.info(f"Scroll message set: {display_message[:50]}...")
		else:
			logger.warning(f"Scroll text widget not available for message: {message[:50]}...")
			
	async def start_quick_game(self, data):
		"""Handle the quick_game event to initialize a Quick Game."""
		logger.info(f"Starting Quick Game with data: {data}")
		logger.info(f"Received quick_game command with data: {data}")
		
		try:
			# Extract Quick Game data - handle both direct data and nested formats
			if isinstance(data, dict) and 'data' in data:
				game_data = data['data']
			else:
				game_data = data
				
			# Clear any existing game state and UI FIRST
			self._clear_for_new_game()
				
			# Check for redundant type field
			if isinstance(game_data, dict) and 'type' in game_data and game_data.get('type') == 'quick_game':
				game_data_copy = game_data.copy()
				game_data_copy.pop('type', None)
				game_data = game_data_copy
				logger.info("Removed redundant type field from game_data")
				
			# Extract required fields with fallbacks
			bowlers = game_data.get("bowlers", [])
			games = game_data.get("games")
			time = game_data.get("time")
			pre_bowl = game_data.get("pre_bowl", [])
			frames_per_turn = game_data.get('frames_per_turn', 1)
	
			if not bowlers:
				logger.error("No bowlers provided for Quick Game.")
				return
	
			# Create a GameSettings object with proper defaults
			settings = GameSettings(
				background_color="blue",
				foreground_color="white",
				pin_values=[2, 3, 5, 3, 2],
				patterns={
					'11100': 'C\\O',
					'00111': 'C/O',
					'01110': 'A',
					'01111': 'L',
					'11110': 'R',
					'00100': 'HP',
					'01100': 'SL',
					'00110': 'SR',
					'11111': 'X',
					'00000': '-'
				},
				total_games=games,
				total_time=time,
				pre_bowl=pre_bowl,
				frames_per_turn=frames_per_turn,
				bonus_display_mode="separated"
			)
	
			# Ensure game_window exists and is properly configured
			if not hasattr(self, 'game_window') or not self.game_window:
				logger.warning("game_window not found, creating a new one")
				self.game_window = tk.Frame(self, bg=settings.background_color)  # Use game background color
				self.game_window.pack(fill=tk.BOTH, expand=True)
			else:
				# Update the background color of existing game_window
				self.game_window.configure(bg=settings.background_color)
			
			# Verify that game_window is empty
			if self.game_window.winfo_children():
				logger.warning("game_window still has children, clearing again")
				for widget in list(self.game_window.winfo_children()):
					try:
						widget.destroy()
					except:
						pass
				self.game_window.update_idletasks()
				
			# Create the QuickGame instance with proper parent
			self.quick_game = QuickGame(
				bowlers=bowlers,
				settings=settings,
				parent=self
			)
	
			if hasattr(self, 'machine'):
				logger.info("Machine symbol popup callback should be set by game")
	
			# Start the game
			self.quick_game.start()
			logger.info(f"Quick Game started with bowlers: {bowlers}")
	
			# Update UI
			self.set_scroll_message("Have A Great Game!!")
			self.set_info_label(f"Games: {games if games else 'Time mode'}")
			
			# Set up the ball detector 
			self.setup_ball_detector()
			
			# Update lane status
			self.update_lane_status("active")
	
		except Exception as e:
			logger.error(f"Error starting Quick Game: {e}")
			import traceback
			logger.error(f"Traceback: {traceback.format_exc()}")

	def run(self):
		self.mainloop()
			
	def setup_ball_detector(self):
		"""Initialize the BallDetector with the current game - ENHANCED for reconnection."""
		# Check for either quickgame or league game
		active_game = None
		if hasattr(self, 'league_game') and self.league_game:
			active_game = self.league_game
			logger.info("Setting up ball detector for league game")
		elif hasattr(self, 'quick_game') and self.quick_game:
			active_game = self.quick_game
			logger.info("Setting up ball detector for quick game")
		
		if active_game:
			# Import the ActiveBallDetector
			from active_ball_detector import ActiveBallDetector
			
			# ENHANCED: If ball detector already exists, just update its game reference
			if hasattr(self, 'ball_detector') and self.ball_detector:
				logger.info("Ball detector exists - updating game reference")
				self.ball_detector.game = active_game
				
				# Ensure it's not suspended
				if hasattr(self.ball_detector, 'set_suspended'):
					self.ball_detector.set_suspended(False)
				
				logger.info("Ball detector game reference updated")
				return True
			else:
				# Create a new ball detector
				logger.info("Creating new ball detector")
				self.ball_detector = ActiveBallDetector(active_game, self.machine)
				logger.info(f"Ball detector created for {type(active_game).__name__}")
				return True
		else:
			logger.error("Cannot initialize ball detector: No active game")
			return False

	async def start_league_game(self, data):
		"""Handle the league_game event to initialize a League Game."""
		logger.info(f"Starting League Game with data: {data}")
		try:
			# Check if 'data' field exists and extract it
			if isinstance(data, dict) and 'data' in data:
				actual_data = data['data']
			else:
				actual_data = data
				
			# Clear any existing game state and UI FIRST
			self._clear_for_new_game()
				
			# Log the actual data we're using
			logger.info(f"Actual game data being used: {json.dumps(actual_data)[:200]}...")
			
			bowlers = actual_data.get("bowlers", [])
			paired_lane = actual_data.get("paired_lane")
			frames_per_turn = actual_data.get("frames_per_turn", 5)
			games = actual_data.get("games", 3)
			settings = actual_data.get("settings", {})
	
			if not bowlers:
				logger.error("No bowlers provided for League Game.")
				return
			
			# Extract total_display from settings before creating GameSettings
			total_display = settings.get("total_display", "regular")
			logger.info(f"Extracted total_display setting: {total_display}")
	
			# Create GameSettings from provided settings or use defaults
			if settings:
				game_settings = GameSettings(
					background_color=settings.get("background_color", "blue"),
					foreground_color=settings.get("foreground_color", "white"),
					pin_values=settings.get("pin_values", [2, 3, 5, 3, 2]),
					patterns=settings.get("patterns", {
						'11100': 'C\\O',  # Left pins (lTwo + lThree)  
						'00111': 'C/O',   # Right pins (cFive + rThree + rTwo)
						'01110': 'A',	 # Middle (lThree + cFive + rThree)
						'10000': 'L',	 # lTwo only
						'00001': 'R',	 # rTwo only  
						'00100': 'HP',	# cFive only
						'01100': 'SL',	# lThree + cFive
						'00110': 'SR',	# cFive + rThree
						'11111': 'X',	 # Strike
						'00000': '-'	  # Miss
					}),
					frames_per_turn=frames_per_turn,
					total_games=games,
					total_time=None,
					pre_bowl=settings.get("pre_bowl", []),
					bonus_display_mode=settings.get("bonus_display_mode", "separated")
				)
				
				game_settings.total_display = total_display
				
			else:
				# Default settings
				game_settings = GameSettings(
					background_color="blue",
					foreground_color="white",
					pin_values=[2, 3, 5, 3, 2],
					patterns={
						'11100': 'C\\O',  # Left pins (lTwo + lThree)  
						'00111': 'C/O',   # Right pins (cFive + rThree + rTwo)
						'01110': 'A',	 # Middle (lThree + cFive + rThree)
						'10000': 'L',	 # lTwo only
						'00001': 'R',	 # rTwo only  
						'00100': 'HP',	# cFive only
						'01100': 'SL',	# lThree + cFive
						'00110': 'SR',	# cFive + rThree
						'11111': 'X',	 # Strike
						'00000': '-'	  # Miss
					},
					frames_per_turn=frames_per_turn,
					total_games=games,
					total_time=None,
					pre_bowl=[]
				)
				
				game_settings.total_display = "regular"
	
			# Initialize the League Game
			self.league_game = LeagueGame(
				bowlers=bowlers,
				settings=game_settings,
				paired_lane=paired_lane,
				parent=self
			)
			
			# Ensure machine has the symbol popup callback set
			if hasattr(self, 'machine'):
				# The LeagueGame __init__ should have already set this up
				logger.info("Machine symbol popup callback should be set by league game")
	
			# Start the League Game
			self.league_game.start()
			logger.info(f"League Game started with bowlers: {[b.get('name', b) for b in bowlers]}")
	
			# Update the UI
			if paired_lane:
				self.set_game_display(f"League Game: Paired with Lane {paired_lane}")
			else:
				self.set_game_display(f"League Game: {', '.join([b.get('name', b) for b in bowlers])}")
			
			self.set_info_label(f"Games: {games}, Frames per turn: {frames_per_turn}")
			
			# Set up the ball detector for the league game
			self.setup_ball_detector()
	
		except Exception as e:
			logger.error(f"Error starting League Game: {e}")
			import traceback
			logger.error(f"Traceback: {traceback.format_exc()}")
			
	def handle_request_machine_status(self, data=None):
		"""Handle request for machine status and send it back through dispatcher."""
		machine = MachineFunctions()
		status_data = {
			'control': machine.control.copy(),
			'control_change': machine.control_change.copy()
		}
		
		# Send status back through dispatcher
		if 'machine_status_response' in dispatcher.listeners:
			dispatcher.listeners['machine_status_response'][0](status_data)

	def handle_bowler_move(self, data):
		"""Handle a bowler moving between lanes during league play"""
		logger.info(f"Handling bowler move: {data}")
		
		# If we have an active league game, delegate to it
		if hasattr(self, 'league_game') and self.league_game:
			self.league_game.handle_bowler_move(data)
		else:
			logger.warning("Received bowler_move event but no active league game")

	def handle_frame_update(self, data):
		"""Handle a frame update from paired lane during league play"""
		logger.info(f"Handling frame update: {data}")
		
		# If we have an active league game, delegate to it
		if hasattr(self, 'league_game') and self.league_game:
			self.league_game.handle_frame_update(data)
		else:
			logger.warning("Received frame_update event but no active league game")

	def handle_game_complete(self, data):
		"""Handle a game complete notification from paired lane"""
		logger.info(f"Handling game complete notification: {data}")
		
		# If we have an active league game, delegate to it
		if hasattr(self, 'league_game') and self.league_game:
			self.league_game.handle_game_complete(data)
		else:
			logger.warning("Received game_complete event but no active league game")

	def handle_toggle_hold(self, data=None):
		"""Handle the hold_game event to toggle hold state."""
		logger.info(f"Handling toggle hold with data: {data}")
		
		# Toggle hold state in the active game
		if hasattr(self, 'quick_game') and self.quick_game:
			self.quick_game.toggle_hold()
		elif hasattr(self, 'league_game') and self.league_game:
			self.league_game.toggle_hold()
		else:
			logger.warning("No active game to toggle hold state")
			
	def handle_end_game_request(self, data=None):
		"""Handle end game request from server - terminates any active game"""
		logger.info(f"Received end game request from server: {data}")
		
		try:
			# Extract end game parameters
			force_end = data.get('force_end', True) if data else True
			reason = data.get('reason', 'Server request') if data else 'Server request'
			clear_data = data.get('clear_data', True) if data else True
			
			logger.info(f"Processing end game request - Force: {force_end}, Reason: {reason}, Clear: {clear_data}")
			
			# Determine which game is active and end it appropriately
			game_ended = False
			
			# Check for active Quick Game
			if hasattr(self, 'quick_game') and self.quick_game and hasattr(self.quick_game, 'game_started') and self.quick_game.game_started:
				logger.info("Ending active Quick Game")
				self._end_quick_game(force_end, reason, clear_data)
				game_ended = True
			
			# Check for active League Game
			elif hasattr(self, 'league_game') and self.league_game and hasattr(self.league_game, 'game_started') and self.league_game.game_started:
				logger.info("Ending active League Game")
				self._end_league_game(force_end, reason, clear_data)
				game_ended = True
			
			# If no active game found, just clear everything
			if not game_ended:
				logger.info("No active game found - performing complete system reset")
				self._perform_complete_reset(reason)
			
			# Update UI displays
			self._update_displays_after_end_game(reason)
			
			# Update lane status
			self.update_lane_status("idle")
			
			logger.info(f"End game request completed successfully - Reason: {reason}")
			
		except Exception as e:
			logger.error(f"Error handling end game request: {e}")
			# Fallback: force complete reset
			try:
				self._perform_complete_reset("Error during end game")
			except Exception as fallback_error:
				logger.error(f"Fallback reset also failed: {fallback_error}")

	def handle_start_practice_game(self, data):
		"""Handle the practice_game event to initialize a Practice Game."""
		logger.info(f"Starting Practice Game with data: {data}")
		
		try:
			# Extract practice game data
			if isinstance(data, dict) and 'data' in data:
				game_data = data['data']
			else:
				game_data = data
			
			# Clear any existing game state
			self._clear_for_new_game()
			
			# Extract time setting (number represents 30-minute blocks)
			time_blocks = game_data.get("time", 1)  # Default to 1 block (30 minutes)
			
			# Create GameSettings for practice
			settings = GameSettings(
				background_color="blue",
				foreground_color="white",
				pin_values=[2, 3, 5, 3, 2],
				patterns={
					'11100': 'C\\O',
					'00111': 'C/O',
					'01110': 'A',
					'01111': 'L',
					'11110': 'R',
					'00100': 'HP',
					'01100': 'SL',
					'00110': 'SR',
					'11111': 'X',
					'00000': '-'
				},
				total_time=time_blocks  # Used to calculate practice duration
			)
			
			# Create the practice game
			self.practice_game = PracticeGame(settings=settings, parent=self)
			
			# Start the practice
			self.practice_game.start()
			logger.info(f"Practice Game started for {time_blocks * 30} minutes")
			
			# Update lane status
			self.update_lane_status("practice")
			
		except Exception as e:
			logger.error(f"Error starting Practice Game: {e}")
			import traceback
			logger.error(f"Traceback: {traceback.format_exc()}")

	def start_hangman_game(self, data):
		pass
		'''
		"""Handle the start_new_game event to initialize a Hangman Bowling game."""
		try:
			bowlers = data.get("bowlers", [])  # List of bowler names
			if not bowlers:
				logger.error("No bowlers provided for Hangman Bowling.")
				return
	
			# Initialize the Hangman Bowling game
			self.hangman_game = HangmanBowling(
				bowlers=bowlers,
				background_color="blue",
				foreground_color="white"
			)
			
			# Clear any existing game state and UI FIRST
			self._clear_for_new_game()
	
			# Start the game
			self.hangman_game.start()
			logger.info(f"Hangman Bowling started with bowlers: {bowlers}")
	
			# Update the UI to reflect the new game
			self.set_game_display(f"Hangman Bowling: {', '.join(bowlers)}")
			self.set_info_label("Press SKIP to start")
	
		except Exception as e:
			logger.error(f"Error starting Hangman Bowling: {e}")
		'''
		
	def _end_quick_game(self, force_end=True, reason="Server request", clear_data=True):
		"""End the active Quick Game properly"""
		try:
			if hasattr(self, 'quick_game') and self.quick_game:
				# Save game data before ending if not forced
				if not force_end and hasattr(self.quick_game, '_save_current_game_data'):
					try:
						self.quick_game._save_current_game_data()
						logger.info("Quick Game data saved before ending")
					except Exception as e:
						logger.warning(f"Could not save Quick Game data: {e}")
				
				# Stop any timers
				if hasattr(self.quick_game, 'timer_running'):
					self.quick_game.timer_running = False
				
				# End the game properly
				if hasattr(self.quick_game, '_end_game'):
					self.quick_game._end_game()
				else:
					# Fallback: set game_started to False
					self.quick_game.game_started = False
				
				# Clear the game reference if requested
				if clear_data:
					del self.quick_game
					logger.info("Quick Game reference cleared")
				
			logger.info(f"Quick Game ended - Reason: {reason}")
			
		except Exception as e:
			logger.error(f"Error ending Quick Game: {e}")
	
	def _end_league_game(self, force_end=True, reason="Server request", clear_data=True):
		"""End the active League Game properly"""
		try:
			if hasattr(self, 'league_game') and self.league_game:
				# Save game data before ending if not forced
				if not force_end and hasattr(self.league_game, '_save_current_game_data'):
					try:
						self.league_game._save_current_game_data()
						logger.info("League Game data saved before ending")
					except Exception as e:
						logger.warning(f"Could not save League Game data: {e}")
				
				# Handle league-specific cleanup
				if hasattr(self.league_game, 'practice_mode'):
					self.league_game.practice_mode = False
				
				# Stop any timers
				if hasattr(self.league_game, 'timer_running'):
					self.league_game.timer_running = False
				
				# End the game properly
				if hasattr(self.league_game, '_end_game'):
					self.league_game._end_game()
				else:
					# Fallback: set game_started to False
					self.league_game.game_started = False
				
				# Clear the game reference if requested
				if clear_data:
					del self.league_game
					logger.info("League Game reference cleared")
			
			logger.info(f"League Game ended - Reason: {reason}")
			
		except Exception as e:
			logger.error(f"Error ending League Game: {e}")
	
	def _perform_complete_reset(self, reason="System reset"):
		"""Perform a complete system reset - clear everything"""
		try:
			logger.info(f"Performing complete system reset - Reason: {reason}")
			
			# Clear any existing games
			if hasattr(self, 'quick_game'):
				del self.quick_game
			if hasattr(self, 'league_game'):
				del self.league_game
			
			# Stop ball detector
			if hasattr(self, 'ball_detector') and self.ball_detector:
				try:
					if hasattr(self.ball_detector, 'set_suspended'):
						self.ball_detector.set_suspended(True)
					del self.ball_detector
					self.ball_detector = None
				except Exception as e:
					logger.warning(f"Error stopping ball detector: {e}")
			
			# Clear the game window completely
			if hasattr(self, 'game_window') and self.game_window:
				# Safely destroy all child widgets
				for widget in list(self.game_window.winfo_children()):
					try:
						widget.destroy()
					except tk.TclError:
						pass
				
				# Force update to ensure clearing is complete
				self.game_window.update_idletasks()
			
			# Reset machine to safe state
			if hasattr(self, 'machine') and self.machine:
				try:
					self.machine.reset_pins()
					logger.info("Machine reset to safe state")
				except Exception as e:
					logger.warning(f"Could not reset machine: {e}")
			
			# Create a clean idle screen
			self._create_idle_screen(reason)
			
			logger.info("Complete system reset finished")
			
		except Exception as e:
			logger.error(f"Error during complete reset: {e}")
	
	def _create_idle_screen(self, reason="System ready"):
		"""Create a clean idle screen showing the system is ready"""
		try:
			if not hasattr(self, 'game_window') or not self.game_window:
				return
			
			# Create idle container
			idle_container = tk.Frame(self.game_window, bg='black')
			idle_container.pack(fill=tk.BOTH, expand=True, padx=50, pady=50)
			
			# Lane title
			lane_title = tk.Label(
				idle_container,
				text=f"LANE {self.lane_id}",
				bg='black',
				fg='white',
				font=("Arial", 48, "bold")
			)
			lane_title.pack(pady=(50, 30))
			
			# Status message
			status_label = tk.Label(
				idle_container,
				text="SYSTEM READY",
				bg='black',
				fg='green',
				font=("Arial", 32, "bold")
			)
			status_label.pack(pady=20)
			
			# Reason for ending (if not default)
			if reason != "System ready":
				reason_label = tk.Label(
					idle_container,
					text=f"Last action: {reason}",
					bg='black',
					fg='yellow',
					font=("Arial", 16)
				)
				reason_label.pack(pady=10)
			
			# Instructions
			instructions = tk.Label(
				idle_container,
				text="Waiting for new game assignment from server",
				bg='black',
				fg='white',
				font=("Arial", 20)
			)
			instructions.pack(pady=20)
			
			# Current time display
			current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
			time_label = tk.Label(
				idle_container,
				text=f"System idle since: {current_time}",
				bg='black',
				fg='gray',
				font=("Arial", 14)
			)
			time_label.pack(side=tk.BOTTOM, pady=30)
			
			logger.info("Idle screen created successfully")
			
		except Exception as e:
			logger.error(f"Error creating idle screen: {e}")
	
	def _update_displays_after_end_game(self, reason):
		"""Update all display elements after ending a game"""
		try:
			# Update main display
			self.set_game_display("No Game Active")
			
			# Update info label
			self.set_info_label("System Ready")
			
			# Update scroll message
			self.set_scroll_message(f"Game ended: {reason}. Waiting for new assignment.")
			
			logger.info("Display elements updated after end game")
			
		except Exception as e:
			logger.error(f"Error updating displays: {e}")
		
	def _clear_for_new_game(self):
		"""Enhanced clearing of existing game state and UI before starting a new game."""
		logger.info("Clearing existing game state for new game")
		
		try:
			# Stop any existing timers
			if hasattr(self, 'timer_running'):
				self.timer_running = False
			
			# Clear any existing games with proper cleanup
			if hasattr(self, 'practice_game') and self.practice_game:
				logger.info("Cleaning up existing practice game")
				if hasattr(self.practice_game, 'cleanup'):
					self.practice_game.cleanup()
				del self.practice_game
			
			if hasattr(self, 'quick_game'):
				if hasattr(self.quick_game, 'game_data') and self.quick_game.game_data:
					logger.info("Saving existing game data before clearing")
				del self.quick_game
				
			if hasattr(self, 'league_game'):
				del self.league_game
			
			# Stop ball detector temporarily
			if hasattr(self, 'ball_detector') and self.ball_detector:
				try:
					if hasattr(self.ball_detector, 'set_suspended'):
						self.ball_detector.set_suspended(True)
				except Exception as e:
					logger.warning(f"Error suspending ball detector: {e}")
			
			# REFINED FIX: Just clear the game_window contents, don't destroy the frame itself
			if hasattr(self, 'game_window') and self.game_window:
				children_to_destroy = list(self.game_window.winfo_children())
				for widget in children_to_destroy:
					try:
						if widget.winfo_exists():
							widget.destroy()
					except tk.TclError as e:
						logger.warning(f"Error destroying widget: {e}")
						continue
					except Exception as e:
						logger.warning(f"Unexpected error destroying widget: {e}")
						continue
				
				# Force immediate update to ensure clearing is complete
				try:
					self.game_window.update_idletasks()
					self.update_idletasks()
				except Exception as e:
					logger.warning(f"Error updating UI after clearing: {e}")
			
			# Reset display states
			if hasattr(self, 'set_game_display'):
				self.set_game_display("Starting New Game...")
			if hasattr(self, 'set_info_label'):
				self.set_info_label("Initializing...")
			
			logger.info("Game state cleared successfully")
			
		except Exception as e:
			logger.error(f"Error clearing game state: {e}")
		 
	def cleanup(self):
		"""Properly clean up resources"""
		if hasattr(self, 'client'):
			self.client.stop()
		if hasattr(self, 'client_thread'):
			self.client_thread.join(timeout=1)
		self.destroy()
		
class MachineFunctions:
	"""
	FIXED: Machine control with proper 3rd ball handling and reset timing
	"""
	_instance = None
	_initialized = False
	
	def __new__(cls):
		"""Singleton pattern to ensure only one instance exists"""
		if cls._instance is None:
			cls._instance = super(MachineFunctions, cls).__new__(cls)
		return cls._instance
	
	def __init__(self):
		"""Initialize the hardware only once"""
		if not self._initialized:
			self._setup_hardware()
			self._initialized = True
		
		# Reset operation tracking
		self.pending_operation = None
		self.pending_data = None
		
		# FIXED: Add flags from old implementation
		self._needs_full_reset = False
		self._force_full_reset = False
		
		# Machine cycle timing tracking
		self.machine_cycle_start_time = None
		self.reset_called_time = None
		
		# NEW: 3rd ball handling
		self.pin_set_enabled = True
		self.pin_set_restore_time = None
		
		# Symbol popup callback
		self.symbol_popup_callback = None
		
		# Game context for ball detection
		self.game_context = None
	
	def _setup_hardware(self):
		"""Setup the hardware interfaces"""
		try:
			# Run i2c detection to ensure bus is ready
			subprocess.call(['i2cdetect', '-y', '1'], stdout=subprocess.DEVNULL)
			
			# Load configuration
			with open('settings.json') as f:
				self.lane_settings = json.load(f)
			
			self.lane_id = self.lane_settings["Lane"]
			logger.info(f"Initializing MachineFunctions for Lane {self.lane_id}")
			
			# Extract GPIO pin numbers
			self.gp1, self.gp2, self.gp3, self.gp4, self.gp5, self.gp6, self.gp7, self.gp8 = [
				int(self.lane_settings[self.lane_id][f"GP{i}"]) for i in range(1, 9)
			]
			
			# Initialize GPIO
			GPIO.setmode(GPIO.BCM)
			GPIO.setup([self.gp1, self.gp2, self.gp3, self.gp4, self.gp5, self.gp6], GPIO.OUT)
			GPIO.setup([self.gp7, self.gp8], GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
			GPIO.output([self.gp1, self.gp2, self.gp3, self.gp4, self.gp5, self.gp6], 1)
			
			# Initialize pin control state (1 = up, 0 = down)
			self.control = {'lTwo': 1, 'lThree': 1, 'cFive': 1, 'rThree': 1, 'rTwo': 1}
			self.control_change = {'lTwo': 0, 'lThree': 0, 'cFive': 0, 'rThree': 0, 'rTwo': 0}
			
			# Initialize ADS converters
			self._init_ads()
			
			# Get pin name mappings from settings
			self.pb10 = self.lane_settings[self.lane_id]["B10"]
			self.pb11 = self.lane_settings[self.lane_id]["B11"]
			self.pb12 = self.lane_settings[self.lane_id]["B12"]
			self.pb13 = self.lane_settings[self.lane_id]["B13"]
			self.pb20 = self.lane_settings[self.lane_id]["B20"]
			
			# Machine timing (simplified)
			self.mp = 8.5
			self._load_calibration()
			
			# State tracking
			self.pin_check = False
			self.pins_changed = False
			
			logger.info(f"MachineFunctions hardware setup complete for Lane {self.lane_id}")
			
		except Exception as e:
			logger.error(f"Failed to initialize MachineFunctions: {e}")
			# Use conservative defaults
			self.mp = 8.5
			self.control = {'lTwo': 1, 'lThree': 1, 'cFive': 1, 'rThree': 1, 'rTwo': 1}
	
	def _init_ads(self):
		"""Initialize the ADS ADC converters"""
		try:
			i2c = busio.I2C(board.SCL, board.SDA)
			self.ads1 = ADS.ADS1115(i2c, address=0x48)
			self.ads2 = ADS.ADS1115(i2c, address=0x49)
			
			# Setup analog inputs
			self.b10 = AIN(self.ads1, ADS.P0)
			self.b11 = AIN(self.ads1, ADS.P1)
			self.b12 = AIN(self.ads1, ADS.P2)
			self.b13 = AIN(self.ads1, ADS.P3)
			self.b20 = AIN(self.ads2, ADS.P0)
			self.b21 = AIN(self.ads2, ADS.P1)
			
			logger.info("ADS ADC converters initialized successfully")
			
		except Exception as e:
			logger.error(f"ADS initialization failed: {e}")
			raise
	
	def _load_calibration(self):
		"""Load stored calibration or use default"""
		try:
			with open('settings.json', 'r') as f:
				settings = json.load(f)
			
			lane_id = str(self.lane_id)
			if (lane_id in settings and 
				"B21Calibration" in settings[lane_id] and 
				"MPValue" in settings[lane_id]["B21Calibration"]):
				# TODO: Restore this: self.mp = settings[lane_id]["B21Calibration"]["MPValue"]
				logger.info(f"Using stored MP timing: {self.mp:.2f}s")
			else:
				logger.info("No stored calibration found, using default timing")
				
		except Exception as e:
			logger.warning(f"Error loading calibration: {e}")
	
	def _is_third_ball(self):
		"""Check if this is the 3rd ball of a frame"""
		try:
			if hasattr(self, 'game_context') and self.game_context:
				current_bowler = self.game_context.bowlers[self.game_context.current_bowler_index]
				current_frame = current_bowler.frames[current_bowler.current_frame]
				return len(current_frame.balls) >= 2
			return False
		except Exception as e:
			logger.error(f"Error determining if 3rd ball: {e}")
			return False
	
	def _update_pin_set_status(self):
		"""Update pin_set_enabled status based on timing"""
		current_time = time.time()
		
		# Check if we need to restore pin setting after 8 seconds
		if (not self.pin_set_enabled and 
			self.pin_set_restore_time and 
			current_time >= self.pin_set_restore_time):
			self.pin_set_enabled = True
			self.pin_set_restore_time = None
			logger.info("PIN_SET_RESTORED: Pin setting re-enabled after 8 second delay")
	
	def reset(self):
		try:
			# Record when reset is called for proper MP timing
			self.reset_called_time = time.time()
			self.machine_cycle_start_time = self.reset_called_time
			
			# FIXED: For 3rd balls, disable pin setting for 8 seconds
			if self._is_third_ball():
				self.pin_set_enabled = False
				self.pin_set_restore_time = self.reset_called_time + 8.0
				logger.info("MACHINE_3RD_BALL: Pin setting disabled for 8 seconds")
			
			logger.info("MACHINE_RESET_START: Starting machine cycle with reset")
			GPIO.setup(self.gp6, GPIO.OUT)
			GPIO.output(self.gp6, 0)
			time.sleep(0.05)
			GPIO.output(self.gp6, 1)
			
			logger.info("MACHINE_RESET_COMPLETE: Physical reset completed, machine cycle started")
			return True
			
		except Exception as e:
			logger.error(f"Reset failed: {e}")
			return False
	
	def reset_pins(self):
		"""Reset pins and control state - called by game logic"""
		logger.info("GAME_RESET: Game logic requesting pin reset")
		
		# SET FULL RESET FLAG BEFORE calling reset
		self._force_full_reset = True
		
		# Physical reset
		self.reset()
		
		# Reset control state to all pins UP
		self.control = {'lTwo': 1, 'lThree': 1, 'cFive': 1, 'rThree': 1, 'rTwo': 1}
		self.control_change = {'lTwo': 0, 'lThree': 0, 'cFive': 0, 'rThree': 0, 'rTwo': 0}
		self.pin_check = False
		self.pins_changed = False
		
		# Clear reset flags
		self._needs_full_reset = False
		self._force_full_reset = False
		
		logger.info(f"GAME_RESET_COMPLETE: Pin states reset to: {self.control}")

	def process_throw(self):
		"""CANADIAN 5-PIN: Enhanced process_throw with proper reset logic"""
		process_start_time = time.time()
		logger.info("[0.000s] BALL_DETECTED: Starting hardware processing cycle")
		
		# Update pin set status
		self._update_pin_set_status()
		
		# Step 1: Check pins to see what happened
		result, status = self.check_pins()
		logger.info(f"Pin check result: {result}, Status: {status}")
		
		# Step 2: CANADIAN 5-PIN specific reset logic
		needs_full_reset = False
		is_strike = (status == 2)  # All 5 pins down
		is_third_ball = self._is_third_ball()
		external_force_reset = self._force_full_reset
		
		if external_force_reset:
			logger.info("EXTERNAL_FORCE_RESET: Clearing external force reset flag")
			self._force_full_reset = False
			needs_full_reset = True
		
		# CANADIAN 5-PIN: Determine when full reset is needed
		reset_reason = None
		if external_force_reset:
			needs_full_reset = True
			reset_reason = "external_reset"
		elif is_strike:
			needs_full_reset = True
			reset_reason = "strike_reset"
			logger.info("CANADIAN_5PIN_STRIKE: All 5 pins down - full reset needed")
		elif self._is_frame_ending_ball():
			needs_full_reset = True
			reset_reason = "frame_ending"
			logger.info("CANADIAN_5PIN_FRAME_END: Frame ending ball - full reset needed")
		elif is_third_ball:
			needs_full_reset = True
			reset_reason = "third_ball"
			logger.info("CANADIAN_5PIN_THIRD_BALL: Third ball - full reset needed")
		
		# Step 3: Handle machine cycle based on Canadian 5-pin rules
		if needs_full_reset:
			logger.info(f"RESET_NEEDED: Full reset needed ({reset_reason})")
			self.reset_pins()
		elif self.pins_changed or status > 0:
			logger.info("MACHINE_CYCLE_NEEDED: Starting normal machine cycle")
			self.start_machine_cycle()
		else:
			logger.info("NO_MACHINE_CYCLE: No pin changes detected")
		
		return result
	
	def _is_frame_ending_ball(self):
		"""CANADIAN 5-PIN: Check if this ball ends the current frame"""
		try:
			if hasattr(self, 'game_context') and self.game_context:
				current_bowler = self.game_context.bowlers[self.game_context.current_bowler_index]
				current_frame = current_bowler.frames[current_bowler.current_frame]
				
				current_ball_count = len(current_frame.balls)
				is_10th_frame = (current_bowler.current_frame == 9)
				
				# FIXED: Regular frames (1-9) only end after strike, spare, or 3rd ball
				if not is_10th_frame:
					if current_ball_count == 0:
						# This will be first ball - check if it will be a strike
						return False  # Let the ball be processed first
					elif current_ball_count == 1:
						# This will be second ball - only ends if spare
						# We need to check if this makes a spare
						first_ball_value = current_frame.balls[0].value
						# If first ball was a strike, frame already ended
						if first_ball_value == 15:
							return False  # Frame already ended
						# Otherwise, frame continues regardless of second ball result
						return False  # Always continue to third ball unless spare
					elif current_ball_count == 2:
						# This will be third ball - always ends regular frame
						return True
				
				# CANADIAN 5-PIN: 10th frame rules - NEVER ends early via this function
				else:
					# 10th frame: ONLY ends after 3rd ball, NEVER after 1st or 2nd ball
					# The frame completion logic in process_ball handles 10th frame properly
					if current_ball_count == 2:
						# This will be third ball - always ends 10th frame
						return True
					else:
						# First or second ball in 10th frame - NEVER ends frame here
						return False
			
			return False
		except Exception as e:
			logger.error(f"Error determining frame ending ball: {e}")
			return False
	
	def _will_be_last_ball(self, result, status):
		"""CANADIAN 5-PIN: Determine if this ball will complete the frame"""
		try:
			if hasattr(self, 'game_context') and self.game_context:
				current_bowler = self.game_context.bowlers[self.game_context.current_bowler_index]
				current_frame = current_bowler.frames[current_bowler.current_frame]
				
				current_ball_count = len(current_frame.balls)
				this_ball_value = sum(a * b for a, b in zip(result, [2, 3, 5, 3, 2]))
				is_10th_frame = (current_bowler.current_frame == 9)
				
				# CANADIAN 5-PIN: Strike (15 points) on any ball
				if status == 2 or this_ball_value == 15:
					if not is_10th_frame:
						return True  # Strike ends regular frame
					else:
						# 10th frame: strike doesn't end frame, just resets pins
						return False
				
				# CANADIAN 5-PIN: Regular frames (1-9)
				if not is_10th_frame:
					if current_ball_count == 1:
						# Second ball: check for spare
						first_ball_value = current_frame.balls[0].value
						if first_ball_value + this_ball_value == 15:
							return True  # Spare ends frame
						else:
							return True  # Open frame ends after 2 balls
					elif current_ball_count == 2:
						return True  # Third ball always ends regular frame
				
				# CANADIAN 5-PIN: 10th frame
				else:
					if current_ball_count == 2:
						return True  # Third ball always ends 10th frame
					elif current_ball_count == 1:
						# Second ball in 10th frame
						first_ball_value = current_frame.balls[0].value
						
						# If first ball wasn't a strike and this doesn't make a spare
						if first_ball_value < 15 and (first_ball_value + this_ball_value) < 15:
							return True  # Open frame ends after 2 balls
						# If spare, frame continues for third ball
						# If first ball was strike, frame continues for third ball
						return False
			
			return False
		except Exception as e:
			logger.error(f"Error determining last ball: {e}")
			return False
	
	def start_machine_cycle(self):
		"""CANADIAN 5-PIN: Machine cycle that preserves pin states correctly"""
		
		# Check for full reset flag first
		if getattr(self, '_force_full_reset', False) or getattr(self, '_needs_full_reset', False):
			logger.info("FULL_RESET_FLAG_DETECTED: Executing full reset")
			
			# Full reset: all pins back to UP position
			self.reset()
			self.control = {'lTwo': 1, 'lThree': 1, 'cFive': 1, 'rThree': 1, 'rTwo': 1}
			self.control_change = {'lTwo': 0, 'lThree': 0, 'cFive': 0, 'rThree': 0, 'rTwo': 0}
			
			# Apply configuration immediately
			self.apply_pin_configuration_immediate()
			
			# Clear flags
			self._force_full_reset = False
			self._needs_full_reset = False
			
			logger.info("CANADIAN_5PIN_RESET_COMPLETE: All pins reset to UP position")
			return
		
		# Normal machine cycle: set pins to detected state
		logger.info("MACHINE_CYCLE_START: Starting normal machine cycle")
		if not self.reset():
			logger.error("MACHINE_CYCLE_FAILED: Reset failed")
			return
		
		# Wait for machine timing
		self.wait_for_machine_timing()
		
		# Apply the current pin configuration (keeps knocked down pins down)
		self.apply_pin_configuration()
		
		logger.info(f"CANADIAN_5PIN_CYCLE_COMPLETE: Pin states maintained: {self.control}")
	
	def apply_pin_configuration_immediate(self):
		"""CANADIAN 5-PIN: Apply pin configuration without b21 wait"""
		try:
			logger.info("IMMEDIATE_PIN_CONFIG: Setting all pins to UP state")
			
			# For Canadian 5-pin full reset, all pins go UP
			GPIO.output([self.gp1, self.gp2, self.gp3, self.gp4, self.gp5], 1)
			
			logger.info("CANADIAN_5PIN_IMMEDIATE_COMPLETE: All 5 pins set to UP state")
			
		except Exception as e:
			logger.error(f"IMMEDIATE_PIN_CONFIG_ERROR: {e}")
			# Emergency: all pins to safe UP state
			GPIO.output([self.gp1, self.gp2, self.gp3, self.gp4, self.gp5], 1)
		
	def wait_for_machine_timing(self):
		"""FIXED: Wait for b21 sensor with fallback to pin_restore"""
		if not self.reset_called_time:
			logger.error("TIMING_ERROR: No reset time recorded")
			return
		
		# FIXED: Check if pin setting is disabled
		if not self.pin_set_enabled:
			logger.info("MACHINE_PIN_SET_DISABLED: Pin setting is disabled, skipping b21 wait")
			return
		
		timeout = 8.0  # 8 second timeout
		error_count = 0
		max_errors = 10
		
		logger.info(f"MACHINE_B21_WAIT: Waiting for b21 sensor (max {timeout:.1f}s)")
		
		while time.time() - self.reset_called_time < timeout:
			try:
				if self.b21.voltage >= 4:
					trigger_time = time.time() - self.reset_called_time
					logger.info(f"MACHINE_B21_TRIGGERED: After {trigger_time:.3f}s from reset")
					return  # Success - exit function
					
			except Exception as e:
				error_count += 1
				logger.warning(f"B21 sensor error #{error_count}: {e}")
				
				if error_count >= max_errors:
					logger.error(f"Too many B21 sensor errors ({error_count}), proceeding with pin_restore fallback")
					break
				
				time.sleep(0.01)
				continue
				
			time.sleep(0.01)
		
		# If we get here, b21 was not triggered within timeout
		actual_wait_time = time.time() - self.reset_called_time
		logger.warning(f"MACHINE_B21_TIMEOUT: Waited {actual_wait_time:.3f}s without b21 detection")
		
		# FIXED: Use pin_restore fallback instead of retries
		logger.info("MACHINE_B21_FALLBACK: Using pin_restore with current control state")
		current_control = self.control.copy()
		self.pin_restore(current_control)
		
		logger.info("MACHINE_B21_COMPLETE: Finished b21 wait sequence with fallback")

	def apply_pin_configuration(self):
		try:
			# Start with all pins HIGH (safe state)
			GPIO.output([self.gp1, self.gp2, self.gp3, self.gp4, self.gp5], 1)
			
			# Determine which pins to knock down based on current detection
			pins_to_knock_down = []
			pin_names = []
			
			pin_mapping = {
				'lTwo': self.gp1,
				'lThree': self.gp2,
				'cFive': self.gp3,
				'rThree': self.gp4,
				'rTwo': self.gp5
			}
			
			for pin_name, gpio_pin in pin_mapping.items():
				if self.control.get(pin_name, 1) == 0:
					pins_to_knock_down.append(gpio_pin)
					pin_names.append(pin_name)
			
			if pins_to_knock_down:
				logger.info(f"MACHINE_GPIO_PULSE: Knocking down {pin_names}")
				GPIO.output(pins_to_knock_down, 0)  # Activate solenoids
				time.sleep(0.25)  # Hold pulse
				GPIO.output(pins_to_knock_down, 1)  # Return to safe state
			else:
				logger.info("MACHINE_GPIO_NO_PULSE: All pins remain standing")
			
			logger.info(f"MACHINE_CYCLE_COMPLETE: Final state: {self.control}")
			
		except Exception as e:
			logger.error(f"MACHINE_GPIO_ERROR: {e}")
			# Emergency: all pins to safe state
			GPIO.output([self.gp1, self.gp2, self.gp3, self.gp4, self.gp5], 1)
	
	def check_pins(self):
		"""Check pin sensors and update control state"""
		start_time = time.time()
		min_check_time = 3.0  # 3-second rule compliance
		
		logger.info(f"Starting pin check. Initial state: {self.control}")
		
		# Reset change tracking
		self.control_change = {'lTwo': 0, 'lThree': 0, 'cFive': 0, 'rThree': 0, 'rTwo': 0}
		self.pins_changed = False
		self.pin_check = True
		
		# Check if all pins are already down
		if all(v == 0 for v in self.control.values()):
			logger.info("All pins are already down at start!")
			time.sleep(min_check_time)  # Still wait for rule compliance
			return [1, 1, 1, 1, 1], 2
		
		# Track consecutive stable readings for early exit
		stable_readings = 0
		required_stable = 10
		
		while self.pin_check and time.time() - start_time <= min_check_time:
			try:
				previous_control = self.control.copy()
				
				# Check each sensor with proper timing
				time.sleep(0.025)
				
				# Check sensors in sequence - map to correct pin names
				sensors_to_check = [
					(self.b20, self.pb20),  # Usually cFive
					(self.b13, self.pb13),  # Usually rTwo
					(self.b12, self.pb12),  # Usually rThree
					(self.b11, self.pb11),  # Usually lThree
					(self.b10, self.pb10)   # Usually lTwo
				]
				
				for sensor, pin_name in sensors_to_check:
					try:
						if sensor.voltage >= 4.0 and self.control[pin_name] != 0:
							self.control[pin_name] = 0
							self.control_change[pin_name] = 1
							self.pins_changed = True
							logger.info(f"{pin_name} detected DOWN")
					except Exception as e:
						logger.warning(f"Error reading {pin_name} sensor: {e}")
						continue
				
				# Check for stability (no changes in recent readings)
				if self.control == previous_control:
					stable_readings += 1
				else:
					stable_readings = 0
				
				# Check if all pins are now down (STRIKE!)
				if all(v == 0 for v in self.control.values()):
					remaining_time = min_check_time - (time.time() - start_time)
					if remaining_time > 0:
						logger.info(f"STRIKE! All pins down, waiting remaining {remaining_time:.2f}s for rule compliance")
						time.sleep(remaining_time)
					logger.info("STRIKE detected - all pins are down!")
					return list(self.control_change.values()), 2
				
				# Early exit if stable for sufficient time and some time has passed
				if (stable_readings >= required_stable and 
					time.time() - start_time >= 1.0 and 
					self.pins_changed):
					logger.info(f"Stable state detected after {stable_readings} readings")
					break
				
				time.sleep(0.025)  # Small delay between readings
				
			except Exception as e:
				logger.error(f"Error during pin check: {e}")
				time.sleep(0.01)
				continue
		
		# Pin check complete
		self.pin_check = False
		result = list(self.control_change.values())
		
		logger.info(f"Pin check complete after {time.time() - start_time:.2f}s")
		logger.info(f"Final control state: {self.control}")
		logger.info(f"Changes detected: {result}")
		
		return result, 1 if self.pins_changed else 0
	
	def schedule_reset(self, reset_type='FULL_RESET', data=None):
		"""
		FIXED: Schedule a reset operation with immediate execution support
		"""
		immediate = data.get('immediate', False) if data and isinstance(data, dict) else False
		logger.info(f"RESET_SCHEDULED: {reset_type} scheduled, immediate: {immediate}")
		
		if immediate and reset_type == 'FULL_RESET':
			# Do immediate full reset (for button presses)
			logger.info("IMMEDIATE_FULL_RESET: Executing reset immediately")
			self.reset_pins()
		elif reset_type == 'FULL_RESET':
			# Set flag for full reset to be applied at next machine cycle
			self._force_full_reset = True
			logger.info("FULL_RESET_FLAG_SET: Will be applied at next cycle")
		else:
			# For other reset types, just call reset_pins
			self.reset_pins()
	
	def schedule_pin_restore(self, pin_data):
		"""Schedule a pin restore operation"""
		logger.info(f"PIN_RESTORE_SCHEDULED: {pin_data}")
		
		if pin_data and isinstance(pin_data, dict):
			for key, value in pin_data.items():
				if key in self.control:
					self.control[key] = value
		
		# Start machine cycle to apply the new pin configuration
		self.start_machine_cycle()
	
	def pin_restore(self, data=None):
		"""Pin restore that properly starts machine cycle"""
		logger.info(f"pin_restore called with data: {data}")
		
		if data and isinstance(data, dict):
			# Update control state with provided data
			for key, value in data.items():
				if key in self.control:
					self.control[key] = value
					logger.info(f"Set {key} to {value}")
			
			logger.info(f"Updated control state: {self.control}")
			
			# Start machine cycle to apply the configuration
			self.start_machine_cycle()
		else:
			logger.info("pin_restore called without data - no action taken")
	
	def _is_tenth_frame_complete(self, frame, result, status):
		"""Check if 10th frame is complete after this ball"""
		current_balls = len(frame.balls)
		
		# If this is the third ball, frame is complete
		if current_balls >= 2:
			return True
		
		# If this is the second ball and no strike/spare in first two, frame is complete
		if current_balls == 1:
			first_ball_value = frame.balls[0].value
			this_ball_value = sum(a * b for a, b in zip(result, [2, 3, 5, 3, 2]))
			
			# No strike on first ball and no spare = frame complete
			if first_ball_value < 15 and (first_ball_value + this_ball_value) < 15:
				return True
		
		return False
	
	def pin_set(self, pin_data):

		logger.info(f"pin_set called with direct control data: {pin_data}")
		
		# Update control state directly from function call
		self.control = pin_data.copy()
		logger.info(f"Updated control state to: {self.control}")
		
		# Start machine cycle with direct control (bypasses all timing restrictions)
		self._start_machine_cycle_direct(pin_data)
	
	def _start_machine_cycle_direct(self, pin_control):

		logger.info("MACHINE_CYCLE_DIRECT: Starting direct pin control cycle")
		logger.info(f"MACHINE_CYCLE_DIRECT: Target pin states: {pin_control}")
		
		# BYPASS all timing restrictions
		original_pin_setting_enabled = self.pin_setting_enabled
		self.pin_setting_enabled = True  # Force enable for direct control
		
		# Do machine reset first using existing reset code
		logger.info("MACHINE_CYCLE_DIRECT: Performing reset before direct pin setting")
		GPIO.output(self.gp6, 0)
		time.sleep(0.05)
		GPIO.output(self.gp6, 1)
		logger.info("MACHINE_CYCLE_DIRECT: Reset pulse sent")
		
		# Set the control state to desired configuration
		self.control = pin_control.copy()
		
		# Execute direct pin setting
		self._execute_direct_pin_setting(pin_control)
		
		# Restore original pin setting state
		self.pin_setting_enabled = original_pin_setting_enabled
		
		logger.info(f"MACHINE_CYCLE_DIRECT_COMPLETE: Final achieved state: {self.control}")
	
	def _execute_direct_pin_setting(self, pin_control):

		logger.info("MACHINE_DIRECT_PIN_SET: Starting direct mechanical pin setting")
		
		# Wait for b21 sensor if pin setting is normally enabled
		if hasattr(self, '_wait_for_b21_sensor'):
			try:
				logger.info("MACHINE_DIRECT_PIN_SET: Waiting for b21 sensor")
				self._wait_for_b21_sensor(timeout=8.0)
				logger.info("MACHINE_DIRECT_PIN_SET: b21 sensor ready")
			except Exception as e:
				logger.warning(f"MACHINE_DIRECT_PIN_SET: b21 sensor issue: {e}, proceeding anyway")
		else:
			# Wait for the standard b21 timing if no separate function exists
			time.sleep(5.5)  # Standard b21 wait time
			logger.info("MACHINE_DIRECT_PIN_SET: Standard b21 wait completed")
		
		# Execute pin positioning using existing GPIO pins
		pins_to_knock_down = []
		
		for pin_name, desired_state in pin_control.items():
			if desired_state == 0:  # Pin should be down
				pins_to_knock_down.append(pin_name)
		
		logger.info(f"MACHINE_DIRECT_PIN_SET: Pins to knock down: {pins_to_knock_down}")
		
		# Execute GPIO pulses using existing pin mappings
		if pins_to_knock_down:
			logger.info(f"MACHINE_DIRECT_GPIO_PULSE: Knocking down {pins_to_knock_down}")
			
			for pin_name in pins_to_knock_down:
				# Use existing GPIO pin mappings from MachineFunctions
				gpio_pin = None
				
				# Map pin names to existing GPIO variables in MachineFunctions
				if pin_name == 'lTwo' and hasattr(self, 'gp12'):
					gpio_pin = self.gp12
				elif pin_name == 'lThree' and hasattr(self, 'gp16'):
					gpio_pin = self.gp16
				elif pin_name == 'cFive' and hasattr(self, 'gp20'):
					gpio_pin = self.gp20
				elif pin_name == 'rThree' and hasattr(self, 'gp21'):
					gpio_pin = self.gp21
				elif pin_name == 'rTwo' and hasattr(self, 'gp26'):
					gpio_pin = self.gp26
				
				if gpio_pin is not None:
					try:
						# Use existing GPIO pulse pattern
						GPIO.output(gpio_pin, 0)
						time.sleep(0.15)  # Slightly longer pulse for direct control
						GPIO.output(gpio_pin, 1)
						logger.info(f"MACHINE_DIRECT_GPIO: Pulsed {pin_name} on GPIO {gpio_pin}")
					except Exception as e:
						logger.error(f"MACHINE_DIRECT_GPIO_ERROR: Failed to pulse {pin_name}: {e}")
				else:
					logger.error(f"MACHINE_DIRECT_GPIO_ERROR: No GPIO pin found for {pin_name}")
		
		# Brief settling time
		time.sleep(0.5)
		
		logger.info(f"MACHINE_DIRECT_PIN_SET_COMPLETE: Target state achieved: {pin_control}")
	
	def emergency_pin_reset(self):
		
		logger.info("EMERGENCY_PIN_RESET: Resetting all pins to standing position")
		all_pins_up = {'lTwo': 1, 'lThree': 1, 'cFive': 1, 'rThree': 1, 'rTwo': 1}
		self.pin_set(all_pins_up)
	
		
class MachineFunctionsOld:
	
	_instance = None
	_initialized = False
	
	def __new__(cls):
		"""Singleton pattern to ensure only one instance exists"""
		if cls._instance is None:
			cls._instance = super(MachineFunctions, cls).__new__(cls)
		return cls._instance
	
	def __init__(self):
		"""Initialize the hardware only once"""
		if not self._initialized:
			self._setup_hardware()
			self._initialized = True
		
		# Reset operation tracking
		self.pending_operation = None
		self.pending_data = None
		
		# Reset flags
		self._needs_full_reset = False
		self._force_full_reset = False
		
		# Machine cycle timing tracking
		self.machine_cycle_start_time = None
		self.reset_called_time = None
		
		# 3rd ball handling
		self.pin_set_enabled = True
		self.pin_set_restore_time = None
		
		# Symbol popup callback
		self.symbol_popup_callback = None
	
	def _setup_hardware(self):
		"""Setup the hardware interfaces"""
		try:
			# Run i2c detection to ensure bus is ready
			subprocess.call(['i2cdetect', '-y', '1'], stdout=subprocess.DEVNULL)
			
			# Load configuration
			with open('settings.json') as f:
				self.lane_settings = json.load(f)
			
			self.lane_id = self.lane_settings["Lane"]
			logger.info(f"Initializing MachineFunctions for Lane {self.lane_id}")
			
			# Extract GPIO pin numbers
			self.gp1, self.gp2, self.gp3, self.gp4, self.gp5, self.gp6, self.gp7, self.gp8 = [
				int(self.lane_settings[self.lane_id][f"GP{i}"]) for i in range(1, 9)
			]
			
			# Initialize GPIO
			GPIO.setmode(GPIO.BCM)
			GPIO.setup([self.gp1, self.gp2, self.gp3, self.gp4, self.gp5, self.gp6], GPIO.OUT)
			GPIO.setup([self.gp7, self.gp8], GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
			GPIO.output([self.gp1, self.gp2, self.gp3, self.gp4, self.gp5, self.gp6], 1)
			
			# Initialize pin control state (1 = up, 0 = down)
			self.control = {'lTwo': 1, 'lThree': 1, 'cFive': 1, 'rThree': 1, 'rTwo': 1}
			self.control_change = {'lTwo': 0, 'lThree': 0, 'cFive': 0, 'rThree': 0, 'rTwo': 0}
			
			# Initialize ADS converters
			self._init_ads()
			
			# Get pin name mappings from settings
			self.pb10 = self.lane_settings[self.lane_id]["B10"]
			self.pb11 = self.lane_settings[self.lane_id]["B11"]
			self.pb12 = self.lane_settings[self.lane_id]["B12"]
			self.pb13 = self.lane_settings[self.lane_id]["B13"]
			self.pb20 = self.lane_settings[self.lane_id]["B20"]
			
			# Machine timing (simplified)
			self.mp = 8.5
			self._load_calibration()
			
			# State tracking
			self.pin_check = False
			self.pins_changed = False
			
			logger.info(f"MachineFunctions hardware setup complete for Lane {self.lane_id}")
			
		except Exception as e:
			logger.error(f"Failed to initialize MachineFunctions: {e}")
			# Use conservative defaults
			self.mp = 8.5
			self.control = {'lTwo': 1, 'lThree': 1, 'cFive': 1, 'rThree': 1, 'rTwo': 1}
	
	def _init_ads(self):
		"""Initialize the ADS ADC converters"""
		try:
			i2c = busio.I2C(board.SCL, board.SDA)
			self.ads1 = ADS.ADS1115(i2c, address=0x48)
			self.ads2 = ADS.ADS1115(i2c, address=0x49)
			
			# Setup analog inputs
			self.b10 = AIN(self.ads1, ADS.P0)
			self.b11 = AIN(self.ads1, ADS.P1)
			self.b12 = AIN(self.ads1, ADS.P2)
			self.b13 = AIN(self.ads1, ADS.P3)
			self.b20 = AIN(self.ads2, ADS.P0)
			self.b21 = AIN(self.ads2, ADS.P1)
			
			logger.info("ADS ADC converters initialized successfully")
			
		except Exception as e:
			logger.error(f"ADS initialization failed: {e}")
			raise
	
	def _load_calibration(self):
		"""Load stored calibration or use default"""
		try:
			with open('settings.json', 'r') as f:
				settings = json.load(f)
			
			lane_id = str(self.lane_id)
			if (lane_id in settings and 
				"B21Calibration" in settings[lane_id] and 
				"MPValue" in settings[lane_id]["B21Calibration"]):
				# TODO: Restore this: self.mp = settings[lane_id]["B21Calibration"]["MPValue"]
				logger.info(f"Using stored MP timing: {self.mp:.2f}s")
			else:
				logger.info("No stored calibration found, using default timing")
				
		except Exception as e:
			logger.warning(f"Error loading calibration: {e}")
			
	def _is_last_ball(self):
		"""Check if this is the 3rd ball of a frame"""
		try:
			if hasattr(self, 'game_context') and self.game_context:
				current_bowler = self.game_context.bowlers[self.game_context.current_bowler_index]
				current_frame = current_bowler.frames[current_bowler.current_frame]
				return len(current_frame.balls) >= 2
			return False
		except Exception as e:
			logger.error(f"Error determining if 3rd ball: {e}")
			return False
	
	def _update_pin_set_status(self):
		"""Update pin_set_enabled status based on timing"""
		current_time = time.time()
		
		# Check if we need to restore pin setting after 8 seconds
		if (not self.pin_set_enabled and 
			self.pin_set_restore_time and 
			current_time >= self.pin_set_restore_time):
			self.pin_set_enabled = True
			self.pin_set_restore_time = None
			logger.info("PIN_SET_RESTORED: Pin setting re-enabled after 8 second delay")
	
	def reset(self):
		try:
			# Record when reset is called for proper MP timing
			self.reset_called_time = time.time()
			self.machine_cycle_start_time = self.reset_called_time
			
			#  For Final balls, disable pin setting for 8 seconds
			if self._is_last_ball():
				self.pin_set_enabled = False
				self.pin_set_restore_time = self.reset_called_time + 8.0
				logger.info("MACHINE_3RD_BALL: Pin setting disabled for 8 seconds")
			
			logger.info("MACHINE_RESET_START: Starting machine cycle with reset")
			GPIO.setup(self.gp6, GPIO.OUT)
			GPIO.output(self.gp6, 0)
			time.sleep(0.05)
			GPIO.output(self.gp6, 1)
			
			logger.info("MACHINE_RESET_COMPLETE: Physical reset completed, machine cycle started")
			return True
			
		except Exception as e:
			logger.error(f"Reset failed: {e}")
			return False
	
	def reset_pins(self):
		"""Reset pins and control state - called by game logic"""
		logger.info("GAME_RESET: Game logic requesting pin reset")
		
		# SET FULL RESET FLAG BEFORE calling reset
		self._force_full_reset = True
		
		# Physical reset
		self.reset()
		
		# Reset control state to all pins UP
		self.control = {'lTwo': 1, 'lThree': 1, 'cFive': 1, 'rThree': 1, 'rTwo': 1}
		self.control_change = {'lTwo': 0, 'lThree': 0, 'cFive': 0, 'rThree': 0, 'rTwo': 0}
		self.pin_check = False
		self.pins_changed = False
		
		# Clear reset flags
		self._needs_full_reset = False
		self._force_full_reset = False
		
		logger.info(f"GAME_RESET_COMPLETE: Pin states reset to: {self.control}")
	
	def process_throw(self):
		"""Enhanced process_throw - purely hardware focused, no symbol logic."""
		process_start_time = time.time()
		logger.info("[0.000s] BALL_DETECTED: Starting hardware processing cycle")
		
		# Update pin set status
		self._update_pin_set_status()
		
		# Step 1: Check pins to see what happened
		result, status = self.check_pins()
		logger.info(f"Pin check result: {result}, Status: {status}")
		
		# Step 2: Determine if this will be the last ball of the frame EARLY
		is_last_ball = self._will_be_last_ball(result, status)
		is_final_ball = self._is_last_ball()
		
		if is_last_ball:
			logger.info("LAST_BALL_DETECTED: Setting full reset flag for next cycle")
			self._needs_full_reset = True
		
		# For 3rd balls, always set full reset flag to ensure proper reset
		if is_final_ball:
			logger.info("THIRD_BALL_DETECTED: Setting full reset flag to ensure proper frame transition")
			self._needs_full_reset = True
		
		# Step 3: Handle machine cycle based on results
		if status == 2:  # All pins down (STRIKE)
			logger.info("All Pins Down: Setting full reset flag")
			self._needs_full_reset = True
		
		# Step 4: Handle machine cycle - check for last ball first
		if self._needs_full_reset or self._force_full_reset:
			logger.info("LAST_BALL_RESET: Immediate full reset needed - bypassing normal machine cycle")
			self.reset_pins()
		elif self.pins_changed or status > 0:
			logger.info("MACHINE_CYCLE_NEEDED: Starting normal machine cycle")
			self.start_machine_cycle()
		else:
			logger.info("NO_MACHINE_CYCLE: No pin changes detected")
		
		return result
	
	def start_machine_cycle(self):
		"""Enhanced machine cycle with proper full reset handling"""
		# Step 1: Check for full reset flag FIRST and handle immediately
		if getattr(self, '_force_full_reset', False) or getattr(self, '_needs_full_reset', False):
			logger.info("FULL_RESET_FLAG_DETECTED: Executing immediate full reset")
			
			# Execute immediate full reset WITHOUT b21 timing
			self.reset()
			
			# Reset control state to all pins UP
			self.control = {'lTwo': 1, 'lThree': 1, 'cFive': 1, 'rThree': 1, 'rTwo': 1}
			self.control_change = {'lTwo': 0, 'lThree': 0, 'cFive': 0, 'rThree': 0, 'rTwo': 0}
			
			# Apply pins immediately without b21 wait
			self.apply_pin_configuration_immediate()
			
			# Clear flags
			self._force_full_reset = False
			self._needs_full_reset = False
			
			logger.info("FULL_RESET_COMPLETE: Immediate full reset executed without b21 timing")
			return
		
		# Step 2: Normal machine cycle with b21 timing for pin setting
		logger.info("MACHINE_CYCLE_START: Starting normal machine cycle with b21 timing")
		if not self.reset():
			logger.error("MACHINE_CYCLE_FAILED: Reset failed")
			return
		
		# Step 3: Wait for machine timing (b21 sensor) only for normal pin setting
		self.wait_for_machine_timing()
		
		# Step 4: Apply pin configuration
		self.apply_pin_configuration()

	def apply_pin_configuration_immediate(self):
		try:
			logger.info("IMMEDIATE_PIN_CONFIG: Applying pins without b21 wait")
			
			# Start with all pins HIGH (safe state)
			GPIO.output([self.gp1, self.gp2, self.gp3, self.gp4, self.gp5], 1)
			
			# For full reset, all pins should remain up, so no further action needed
			logger.info("IMMEDIATE_PIN_CONFIG_COMPLETE: All pins set to UP state")
			
		except Exception as e:
			logger.error(f"IMMEDIATE_PIN_CONFIG_ERROR: {e}")
			# Emergency: all pins to safe state
			GPIO.output([self.gp1, self.gp2, self.gp3, self.gp4, self.gp5], 1)
	
	def wait_for_machine_timing(self):
		if not self.reset_called_time:
			logger.error("TIMING_ERROR: No reset time recorded")
			return
		
		# Check if pin setting is disabled
		if not self.pin_set_enabled:
			logger.info("MACHINE_PIN_SET_DISABLED: Pin setting is disabled, skipping b21 wait")
			return
		
		timeout = 8.0  # 8 second timeout
		b21_triggered = False
		error_count = 0
		max_errors = 10
		
		logger.info(f"MACHINE_B21_WAIT: Waiting for b21 sensor (max {timeout:.1f}s)")
		
		while time.time() - self.reset_called_time < timeout:
			try:
				if self.b21.voltage >= 4:
					trigger_time = time.time() - self.reset_called_time
					b21_triggered = True
					logger.info(f"MACHINE_B21_TRIGGERED: After {trigger_time:.3f}s from reset")
					return  # Success - exit function
					
			except Exception as e:
				error_count += 1
				logger.warning(f"B21 sensor error #{error_count}: {e}")
				
				if error_count >= max_errors:
					logger.error(f"Too many B21 sensor errors ({error_count}), proceeding with pin_restore fallback")
					break
				
				time.sleep(0.01)
				continue
				
			time.sleep(0.01)
		
		# If we get here, b21 was not triggered within timeout
		actual_wait_time = time.time() - self.reset_called_time
		logger.warning(f"MACHINE_B21_TIMEOUT: Waited {actual_wait_time:.3f}s without b21 detection")
		
		# FIXED: Use pin_restore fallback instead of retries
		logger.info("MACHINE_B21_FALLBACK: Using pin_restore with current control state")
		current_control = self.control.copy()
		self.pin_restore(current_control)
		
		logger.info("MACHINE_B21_COMPLETE: Finished b21 wait sequence with fallback")
		
	def apply_pin_configuration(self):
		try:
			# Start with all pins HIGH (safe state)
			GPIO.output([self.gp1, self.gp2, self.gp3, self.gp4, self.gp5], 1)
			
			# Determine which pins to knock down based on current detection
			pins_to_knock_down = []
			pin_names = []
			
			pin_mapping = {
				'lTwo': self.gp1,
				'lThree': self.gp2,
				'cFive': self.gp3,
				'rThree': self.gp4,
				'rTwo': self.gp5
			}
			
			for pin_name, gpio_pin in pin_mapping.items():
				if self.control.get(pin_name, 1) == 0:
					pins_to_knock_down.append(gpio_pin)
					pin_names.append(pin_name)
			
			if pins_to_knock_down:
				logger.info(f"MACHINE_GPIO_PULSE: Knocking down {pin_names}")
				GPIO.output(pins_to_knock_down, 0)  # Activate solenoids
				time.sleep(0.25)  # Hold pulse
				GPIO.output(pins_to_knock_down, 1)  # Return to safe state
			else:
				logger.info("MACHINE_GPIO_NO_PULSE: All pins remain standing")
			
			logger.info(f"MACHINE_CYCLE_COMPLETE: Final state: {self.control}")
			
		except Exception as e:
			logger.error(f"MACHINE_GPIO_ERROR: {e}")
			# Emergency: all pins to safe state
			GPIO.output([self.gp1, self.gp2, self.gp3, self.gp4, self.gp5], 1)
	
	def check_pins(self):
		"""Check pin sensors and update control state"""
		start_time = time.time()
		min_check_time = 3.0  # 3-second rule compliance
		
		logger.info(f"Starting pin check. Initial state: {self.control}")
		
		# Reset change tracking
		self.control_change = {'lTwo': 0, 'lThree': 0, 'cFive': 0, 'rThree': 0, 'rTwo': 0}
		self.pins_changed = False
		self.pin_check = True
		
		# Check if all pins are already down
		if all(v == 0 for v in self.control.values()):
			logger.info("All pins are already down at start!")
			time.sleep(min_check_time)  # Still wait for rule compliance
			return [1, 1, 1, 1, 1], 2
		
		# Track consecutive stable readings for early exit
		stable_readings = 0
		required_stable = 10
		
		while self.pin_check and time.time() - start_time <= min_check_time:
			try:
				previous_control = self.control.copy()
				
				# Check each sensor with proper timing
				time.sleep(0.025)
				
				# Check sensors in sequence - map to correct pin names
				sensors_to_check = [
					(self.b20, self.pb20),  # Usually cFive
					(self.b13, self.pb13),  # Usually rTwo
					(self.b12, self.pb12),  # Usually rThree
					(self.b11, self.pb11),  # Usually lThree
					(self.b10, self.pb10)   # Usually lTwo
				]
				
				for sensor, pin_name in sensors_to_check:
					try:
						if sensor.voltage >= 4.0 and self.control[pin_name] != 0:
							self.control[pin_name] = 0
							self.control_change[pin_name] = 1
							self.pins_changed = True
							logger.info(f"{pin_name} detected DOWN")
					except Exception as e:
						logger.warning(f"Error reading {pin_name} sensor: {e}")
						continue
				
				# Check for stability (no changes in recent readings)
				if self.control == previous_control:
					stable_readings += 1
				else:
					stable_readings = 0
				
				# Check if all pins are now down (STRIKE!)
				if all(v == 0 for v in self.control.values()):
					remaining_time = min_check_time - (time.time() - start_time)
					if remaining_time > 0:
						logger.info(f"STRIKE! All pins down, waiting remaining {remaining_time:.2f}s for rule compliance")
						time.sleep(remaining_time)
					logger.info("STRIKE detected - all pins are down!")
					return list(self.control_change.values()), 2
				
				# Early exit if stable for sufficient time and some time has passed
				if (stable_readings >= required_stable and 
					time.time() - start_time >= 1.0 and 
					self.pins_changed):
					logger.info(f"Stable state detected after {stable_readings} readings")
					break
				
				time.sleep(0.025)  # Small delay between readings
				
			except Exception as e:
				logger.error(f"Error during pin check: {e}")
				time.sleep(0.01)
				continue
		
		# Pin check complete
		self.pin_check = False
		result = list(self.control_change.values())
		
		logger.info(f"Pin check complete after {time.time() - start_time:.2f}s")
		logger.info(f"Final control state: {self.control}")
		logger.info(f"Changes detected: {result}")
		
		return result, 1 if self.pins_changed else 0
	
	def schedule_reset(self, reset_type='FULL_RESET', data=None):
		"""
		FIXED: Schedule a reset operation with immediate execution support
		"""
		immediate = data.get('immediate', False) if data and isinstance(data, dict) else False
		logger.info(f"RESET_SCHEDULED: {reset_type} scheduled, immediate: {immediate}")
		
		if immediate and reset_type == 'FULL_RESET':
			# Do immediate full reset (for button presses)
			logger.info("IMMEDIATE_FULL_RESET: Executing reset immediately")
			self.reset_pins()
		elif reset_type == 'FULL_RESET':
			# Set flag for full reset to be applied at next machine cycle
			self._force_full_reset = True
			logger.info("FULL_RESET_FLAG_SET: Will be applied at next cycle")
		else:
			# For other reset types, just call reset_pins
			self.reset_pins()
	
	def schedule_pin_restore(self, pin_data):
		"""Schedule a pin restore operation"""
		logger.info(f"PIN_RESTORE_SCHEDULED: {pin_data}")
		
		if pin_data and isinstance(pin_data, dict):
			for key, value in pin_data.items():
				if key in self.control:
					self.control[key] = value
		
		# Start machine cycle to apply the new pin configuration
		self.start_machine_cycle()
	
	def pin_restore(self, data=None):
		"""Pin restore that properly starts machine cycle"""
		logger.info(f"pin_restore called with data: {data}")
		
		if data and isinstance(data, dict):
			# Update control state with provided data
			for key, value in data.items():
				if key in self.control:
					self.control[key] = value
					logger.info(f"Set {key} to {value}")
			
			logger.info(f"Updated control state: {self.control}")
			
			# Start machine cycle to apply the configuration
			self.start_machine_cycle()
		else:
			logger.info("pin_restore called without data - no action taken")


	def _will_be_last_ball(self, result, status):
		"""Determine if this ball will complete the frame"""
		try:
			# Get game context if available
			if hasattr(self, 'game_context') and self.game_context:
				current_bowler = self.game_context.bowlers[self.game_context.current_bowler_index]
				current_frame = current_bowler.frames[current_bowler.current_frame]
				
				# Check ball count in current frame
				current_ball_count = len(current_frame.balls)
				
				# Strike on first ball = last ball of frame (except 10th frame)
				if current_ball_count == 0 and status == 2:  # Strike
					return current_bowler.current_frame < 9  # Not 10th frame
				
				# Spare on second ball = last ball of frame (except 10th frame) 
				if current_ball_count == 1:
					first_ball_value = current_frame.balls[0].value
					this_ball_value = sum(a * b for a, b in zip(result, [2, 3, 5, 3, 2]))
					if first_ball_value + this_ball_value == 15:  # Spare
						return current_bowler.current_frame < 9  # Not 10th frame
				
				# Third ball in any frame except 10th = last ball
				if current_ball_count == 2 and current_bowler.current_frame < 9:
					return True
				
				# 10th frame has special rules - check if this completes it
				if current_bowler.current_frame == 9:
					return self._is_tenth_frame_complete(current_frame, result, status)
			
			return False
		except Exception as e:
			logger.error(f"Error determining last ball: {e}")
			return False


	def _is_tenth_frame_complete(self, frame, result, status):
		"""Check if 10th frame is complete after this ball"""
		current_balls = len(frame.balls)
		
		# If this is the third ball, frame is complete
		if current_balls >= 2:
			return True
		
		# If this is the second ball and no strike/spare in first two, frame is complete
		if current_balls == 1:
			first_ball_value = frame.balls[0].value
			this_ball_value = sum(a * b for a, b in zip(result, [2, 3, 5, 3, 2]))
			
			# No strike on first ball and no spare = frame complete
			if first_ball_value < 15 and (first_ball_value + this_ball_value) < 15:
				return True
		
		return False


if __name__ == "__main__":
	#set_mp()
	base_ui = BaseUI(LaneID)
	base_ui.run()