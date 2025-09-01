"""
Created on Fri Feb 21 14:49:06 2025

@author: AlexFogarty
"""

# games1.py - Refactored version with improved architecture
from dataclasses import dataclass
from typing import List, Dict, Optional
import tkinter as tk
import json
import time
import logging
from tkinter import messagebox
from datetime import datetime
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
from event_dispatcher import dispatcher
from symbol_popup import SymbolPopup
from test_ball_simulator import TestBallSimulator

def setup_logging(log_file_path='log.txt', max_log_size=10*1024*1024, backup_count=5):
	# Create formatter for regular log messages
	log_formatter = logging.Formatter(
		'%(asctime)s - %(levelname)s - %(message)s', 
		datefmt='%d/%m/%H:%M'
	)
	 
	# Create console handler and set level
	console_handler = logging.StreamHandler()
	console_handler.setFormatter(log_formatter)
	
	# Create file handler with rotation to manage file size
	file_handler = RotatingFileHandler(
		log_file_path, 
		maxBytes=max_log_size,
		backupCount=backup_count
	)
	file_handler.setFormatter(log_formatter)
	
	# Get the root logger and set its level
	root_logger = logging.getLogger()
	root_logger.setLevel(logging.INFO)
	
	# Remove any existing handlers
	for handler in root_logger.handlers[:]:
		root_logger.removeHandler(handler)
	
	# Add our handlers
	root_logger.addHandler(console_handler)
	root_logger.addHandler(file_handler)
	
	# Add special startup entry with date and entry number
	current_date = datetime.now().strftime('%d/%m/%Y')
	
	# Calculate entry number by counting existing entries in log file
	entry_number = 1
	if os.path.exists(log_file_path):
		with open(log_file_path, 'r') as f:
			for line in f:
				if f"Log {current_date.split('/')[0]}/{current_date.split('/')[1]}" in line and "entry #" in line:
					entry_number += 1
	
	# Log startup message
	root_logger.info(f"Log {current_date} entry #{entry_number}")
	
	return root_logger

logger = setup_logging()

with open('settings.json') as f:
	lane_settings = json.load(f)

@dataclass
class GameSettings:
	background_color: str
	foreground_color: str
	pin_values: List[int]
	patterns: Dict[str, str]
	frames_per_turn: int = 1
	total_games: Optional[int] = None
	total_time: Optional[int] = None
	pre_bowl: Optional[List[str]] = None
	bonus_display_mode: str = "combined" # or separated
	show_bonus_asterisk: bool = True
	show_frame_breakdown: bool = False  
	display_mode: str = "standard"
	strike_streak_mode: bool = False	  # Don't show strike totals until streak breaks
	show_bonus_in_frame: bool = True 	  # Show bonus balls within earning frame

@dataclass
class BallResult:
	pin_config: List[int]  # [0, 1, 1, 0, 0]
	symbol: str			# e.g., "SL"
	value: int			 # e.g., 8

@dataclass
class Frame:
	balls: List[BallResult]  # Up to 3 balls per frame
	total: int			   # Cumulative total for the frame
	is_strike: bool = False  # True if the frame is a strike
	is_spare: bool = False   # True if the frame is a spare
	bonus_balls: List[Dict] = None  # Bonus balls used for this frame (for database)
	base_score: int = 0	  # Base score without bonus
	bonus_score: int = 0	 # Bonus score

	def __post_init__(self):
		if self.bonus_balls is None:
			self.bonus_balls = []

@dataclass
class Bowler:
	name: str
	frames: List[Frame]	 # 10 frames per bowler
	current_frame: int = 0  # Current frame (0-9)
	total_score: int = 0	# Total score for the bowler
	fouls: int = 0		  # Number of fouls
	prize: bool = False	 # Whether the bowler won a prize
	handicap: int = 0	   # Handicap for the bowler
	absent: bool = False	# Whether the bowler is absent
	default_score: int = 0  # Default score per frame for absent bowlers
	game_completed: bool = False  # Whether the bowler has completed their game

@dataclass
class EnhancedBallResult:
	"""Enhanced ball result with running totals for simulation."""
	pin_config: List[int]	# [1,1,0,0,0] - pins knocked down this ball
	symbol: str			  # Display symbol (X, /, A, etc.)
	ball_value: int		  # Points earned by this ball alone
	frame_running_total: int # Running total for the frame after this ball
	cumulative_total: int	# Cumulative game total after this ball (with bonuses)
	is_bonus_ball: bool = False  # True if this ball serves as bonus for previous frame

@dataclass 
class EnhancedFrame:
	"""Enhanced frame with detailed ball tracking."""
	balls: List[EnhancedBallResult]
	total: int			   # Final frame total (cumulative)
	is_strike: bool = False
	is_spare: bool = False
	bonus_details: Dict = None  # Details about bonus calculations

	def __post_init__(self):
		if self.bonus_details is None:
			self.bonus_details = {}

class GameUIManager:
	def __init__(self, frame, bowlers: List[Bowler], settings: GameSettings, parent=None):
		self.frame = frame
		self.bowlers = bowlers
		self.settings = settings
		self.parent = parent
		self.ui_initialized = False
		
		# PERFORMANCE: Cache widget references to avoid repeated lookups
		self._widget_cache = {}
		self._last_update_time = 0
		self._update_debounce_delay = 0.1
		
		'''
		# Ensure new settings have default values if not provided
		if not hasattr(self.settings, 'strike_streak_mode'):
			self.settings.strike_streak_mode = False
		if not hasattr(self.settings, 'show_bonus_in_frame'):
			self.settings.show_bonus_in_frame = True
		'''
		
		# UI component references for updating
		self.header_labels = []
		self.bowler_name_labels = []
		self.frame_subframes = []
		self.ball_labels = []
		self.total_labels = []
		self.bowler_total_labels = []
		self.button_container = None
		self.button_frame = None
		
		# Pin images
		self.pin_up_image = tk.PhotoImage(file="./5pin_up.png")
		self.pin_down_image = tk.PhotoImage(file="./5pin_down.png")
		
		# Button references and callbacks
		self.hold_button = None
		self.skip_button = None
		self.reset_button = None
		self.settings_button = None
		self.reset_callback = None
		self.skip_callback = None
		self.hold_callback = None
		self.settings_callback = None
		self.pin_restore_callback = None
	
	
	def set_button_callbacks(self, on_reset=None, on_skip=None, on_hold=None, 
							on_settings=None, on_pin_restore=None):
		"""Set callbacks for UI buttons"""
		self.reset_callback = on_reset
		self.skip_callback = on_skip
		self.hold_callback = on_hold
		self.settings_callback = on_settings
		self.pin_restore_callback = on_pin_restore

	def render(self, current_bowler_index: int, hold_active: bool = False):
		"""OPTIMIZED: Render with debouncing and selective updates"""
		current_time = time.time()
		
		# PERFORMANCE: Debounce rapid updates
		if current_time - self._last_update_time < self._update_debounce_delay:
			logger.info("UI_DEBOUNCE: Skipping update due to debouncing")
			return
		
		self._last_update_time = current_time
		render_start_time = time.time()
		logger.info(f"RENDER_START: Starting optimized render with current_bowler_index = {current_bowler_index}")
		
		if not self.ui_initialized:
			init_start = time.time()
			logger.info("RENDER_INIT: UI not initialized, initializing structure")
			self._initialize_ui_structure()
			self.ui_initialized = True
			logger.info(f"RENDER_INIT_COMPLETE: UI initialized in {time.time() - init_start:.3f}s")
		
		# PERFORMANCE: Only update data that has changed
		update_start = time.time()
		logger.info(f"RENDER_UPDATE: Updating bowler data with current_bowler_index = {current_bowler_index}")
		self._update_bowler_data_optimized(current_bowler_index)
		logger.info(f"RENDER_UPDATE_COMPLETE: Bowler data updated in {time.time() - update_start:.3f}s")
		
		# Update button states based on game state
		if self.hold_button:
			button_start = time.time()
			self.hold_button.config(bg="green" if not hold_active else "red", 
								text="HOLD" if not hold_active else "RESUME")
			logger.info(f"RENDER_BUTTONS: Button states updated in {time.time() - button_start:.3f}s")
		
		logger.info(f"RENDER_COMPLETE: Full render completed in {time.time() - render_start_time:.3f}s")
			
	def _initialize_ui_structure(self):
		"""Initialize the UI structure once, creating all widgets."""
		# Clear the frame before initializing
		for widget in self.frame.winfo_children():
			widget.destroy()
			
		# Create containers for widgets we'll need to update later
		self.header_labels = []
		self.bowler_name_labels = []
		self.frame_subframes = []
		self.ball_labels = []
		self.total_labels = []
		self.bowler_total_labels = []
		
		# Display headers: "Bowler", "Frame 1" to "Frame 10", and "TOTAL"
		headers = ["Bowler"] + [f"Frame {i + 1}" for i in range(10)] + ["TOTAL"]
		for col, header in enumerate(headers):
			header_label = tk.Label(
				self.frame,
				text=header,
				bg=self.settings.background_color,
				fg=self.settings.foreground_color,
				font=("Arial", 20, "bold"),
				borderwidth=1,
				relief="solid"
			)
			header_label.grid(row=0, column=col, padx=2, pady=2, sticky="nsew")
			self.header_labels.append(header_label)
		
		# Create widgets for all bowlers
		for row, bowler in enumerate(self.bowlers, start=1):
			# Create bowler name label
			bowler_name_label = tk.Label(
				self.frame,
				text=bowler.name,
				bg=self.settings.background_color,
				fg=self.settings.foreground_color,
				font=("Arial", 40, "bold"),
				borderwidth=1,
				relief="solid"
			)
			bowler_name_label.grid(row=row, column=0, padx=2, pady=2, sticky="nsew")
			self.bowler_name_labels.append(bowler_name_label)
			
			# Create frame containers and labels
			bowler_frames = []
			bowler_ball_labels = []
			bowler_total_labels = []
			
			for col in range(1, 11):  # 10 frames
				# Create a sub-frame for each frame
				frame_subframe = tk.Frame(self.frame, bg=self.settings.background_color, borderwidth=1, relief="solid")
				frame_subframe.grid(row=row, column=col, padx=2, pady=2, sticky="nsew")
				bowler_frames.append(frame_subframe)
				
				# Ball results label
				ball_label = tk.Label(
					frame_subframe,
					text="",
					bg=self.settings.background_color,
					fg=self.settings.foreground_color,
					font=("Arial", 15),
					borderwidth=1,
					relief="solid"
				)
				ball_label.pack(fill="both", expand=True)
				bowler_ball_labels.append(ball_label)
				
				# Frame total label
				total_label = tk.Label(
					frame_subframe,
					text="",
					bg=self.settings.background_color,
					fg=self.settings.foreground_color,
					font=("Arial", 25),
					borderwidth=1,
					relief="solid"
				)
				total_label.pack(fill="both", expand=True)
				bowler_total_labels.append(total_label)
			
			# Total score label
			bowler_total_label = tk.Label(
				self.frame,
				text="",
				bg=self.settings.background_color,
				fg=self.settings.foreground_color,
				font=("Arial", 40, "bold"),
				borderwidth=1,
				relief="solid"
			)
			bowler_total_label.grid(row=row, column=11, padx=2, pady=2, sticky="nsew")
			self.bowler_total_labels.append(bowler_total_label)
			
			self.frame_subframes.append(bowler_frames)
			self.ball_labels.append(bowler_ball_labels)
			self.total_labels.append(bowler_total_labels)
		
		# Add buttons at the bottom
		self._add_buttons()

	def _add_buttons(self):
		"""Add HOLD, SKIP, RESET, and SETTINGS buttons at the bottom of the screen."""
		# Create a container frame for the buttons at the bottom
		self.button_container = tk.Frame(self.frame, bg=self.settings.background_color)
		self.button_container.grid(row=len(self.bowlers) + 2, column=0, columnspan=12, sticky="sew")
		
		# Create a frame for the game control buttons
		self.button_frame = tk.Frame(self.button_container, bg=self.settings.background_color)
		self.button_frame.pack(anchor="s", side=tk.BOTTOM, fill=tk.X, padx=5, pady=5)
		
		# Add game control buttons
		self.hold_button = tk.Button(
			self.button_frame,
			text="HOLD",
			bg="red",
			fg="white",
			command=self.hold_callback,
			font=("Arial", 20)
		)
		self.hold_button.pack(side=tk.LEFT, padx=5, pady=5, fill=tk.BOTH, expand=True)
		
		self.skip_button = tk.Button(
			self.button_frame, 
			text="SKIP", 
			bg="yellow", 
			fg="black", 
			command=self.skip_callback, 
			font=("Arial", 20)
		)
		self.skip_button.pack(side=tk.LEFT, padx=5, pady=5, fill=tk.BOTH, expand=True)
		
		self.reset_button = tk.Button(
			self.button_frame, 
			text="RESET", 
			bg="green", 
			fg="white", 
			command=self.reset_callback, 
			font=("Arial", 20)
		)
		self.reset_button.pack(side=tk.LEFT, padx=5, pady=5, fill=tk.BOTH, expand=True)
		
		# Add settings button
		self.settings_button = tk.Button(
			self.button_frame, 
			text="SETTINGS", 
			bg="blue", 
			fg="white", 
			command=self.settings_callback, 
			font=("Arial", 20)
		)
		self.settings_button.pack(side=tk.RIGHT, padx=15, pady=5, fill=tk.BOTH, expand=True)
		
		# TODO: Here's my test button
		'''
		self.test_button = tk.Button(
			self.button_frame,
			text="TEST",
			bg="purple",
			fg="white",
			command=self._open_test_simulator,
			font=("Arial", 20)
		)
		self.test_button.pack(side=tk.RIGHT, padx=25, pady=15, fill=tk.BOTH, expand=True)
		'''

	def set_reset_button_to_pin_restore(self):
		"""Change the reset button to Pin Restore mode"""
		if self.reset_button:
			self.reset_button.config(text="Pin Restore", command=self.pin_restore_callback)
	
	def set_reset_button_to_normal(self):
		"""Change the reset button back to normal reset mode"""
		if self.reset_button:
			self.reset_button.config(text="RESET", command=self.reset_callback)
			
	def _update_bowler_data_optimized(self, current_bowler_index):
		"""OPTIMIZED: Update bowler data with performance improvements"""
		
		logger.info(f"_update_bowler_data_optimized called with current_bowler_index = {current_bowler_index}")
		
		# PERFORMANCE: Batch widget updates to reduce redraws
		updates_batch = []
		
		for bowler_idx, bowler in enumerate(self.bowlers):
			# PERFORMANCE: Only process visible bowlers (pagination could be added here)
			if bowler_idx >= len(self.bowler_name_labels):
				continue
			
			# Highlight current bowler (batch this update)
			if bowler_idx == current_bowler_index and not getattr(bowler, 'game_completed', False):
				updates_batch.append(('bowler_highlight', bowler_idx, "yellow", "black"))
			elif getattr(bowler, 'game_completed', False):
				updates_batch.append(('bowler_highlight', bowler_idx, "green", "white"))
			else:
				updates_batch.append(('bowler_highlight', bowler_idx, self.settings.background_color, self.settings.foreground_color))
			
			# PERFORMANCE: Only update frames that have changed
			for frame_idx in range(min(len(bowler.frames), len(self.ball_labels[bowler_idx]))):
				frame = bowler.frames[frame_idx]
				
				# Create frame display text
				ball_display_text = self._create_ball_display_text_fast(bowler, frame_idx, frame)
				updates_batch.append(('ball_text', bowler_idx, frame_idx, ball_display_text))
				
				# Frame total display
				total_display = self._create_total_display_text_fast(bowler, frame_idx, frame)
				updates_batch.append(('total_text', bowler_idx, frame_idx, total_display))
			
			# Bowler total score
			if bowler_idx < len(self.bowler_total_labels) and hasattr(bowler, 'total_score'):
				updates_batch.append(('bowler_total', bowler_idx, str(bowler.total_score)))
		
		# PERFORMANCE: Apply all updates in one batch to minimize redraws
		self._apply_updates_batch(updates_batch)
	
	def _create_ball_display_text_fast(self, bowler, frame_idx, frame):
		"""PERFORMANCE: Fast ball display text creation"""
		if not hasattr(frame, 'balls') or not frame.balls:
			return ""
		
		display_parts = []
		is_tenth_frame = (frame_idx == 9)
		
		# Add the balls that were actually thrown in this frame
		for ball_idx, ball in enumerate(frame.balls):
			symbol_text = ball.symbol
			
			# PERFORMANCE: Only add bonus indicator if setting is enabled
			if getattr(self.settings, 'show_bonus_asterisk', False):
				if self._ball_used_as_bonus_fast(bowler, frame_idx, ball_idx):
					symbol_text += "*"
			
			display_parts.append(symbol_text)
		
		# PERFORMANCE: Only add bonus balls if setting is enabled
		if getattr(self.settings, 'show_bonus_in_frame', True) and len(frame.balls) > 0:
			if frame.is_strike and not is_tenth_frame:
				bonus_balls = self._get_strike_bonus_balls_for_display_fast(bowler, frame_idx)
				for bonus_ball in bonus_balls:
					display_parts.append(bonus_ball.symbol)
			elif frame.is_spare and not is_tenth_frame:
				bonus_ball = self._get_spare_bonus_ball_for_display_fast(bowler, frame_idx)
				if bonus_ball:
					display_parts.append(bonus_ball.symbol)
		
		return " ".join(display_parts)
	
	def _create_total_display_text_fast(self, bowler, frame_idx, frame):
		"""PERFORMANCE: Fast total display text creation"""
		if not hasattr(frame, 'total') or frame.total <= 0:
			return ""
		
		# PERFORMANCE: Skip strike streak mode calculation unless enabled
		if getattr(self.settings, 'strike_streak_mode', False) and frame.is_strike:
			if self._is_strike_in_active_streak_fast(bowler, frame_idx):
				return "X"
		
		return str(frame.total)
	
	def _apply_updates_batch(self, updates_batch):
		"""PERFORMANCE: Apply all UI updates in one batch"""
		try:
			# Group updates by type for efficiency
			for update_type, *args in updates_batch:
				if update_type == 'bowler_highlight':
					bowler_idx, bg_color, fg_color = args
					self.bowler_name_labels[bowler_idx].config(bg=bg_color, fg=fg_color)
				
				elif update_type == 'ball_text':
					bowler_idx, frame_idx, text = args
					self.ball_labels[bowler_idx][frame_idx].config(text=text)
				
				elif update_type == 'total_text':
					bowler_idx, frame_idx, text = args
					self.total_labels[bowler_idx][frame_idx].config(text=text)
				
				elif update_type == 'bowler_total':
					bowler_idx, text = args
					self.bowler_total_labels[bowler_idx].config(text=text)
			
		except Exception as e:
			logger.error(f"Error in batch updates: {e}")
	
	def _ball_used_as_bonus_fast(self, bowler, frame_idx, ball_idx):
		"""PERFORMANCE: Fast bonus ball check - simplified logic"""
		# PERFORMANCE: Skip expensive bonus calculations unless really needed
		if not getattr(self.settings, 'show_bonus_asterisk', False):
			return False
		
		# Simple check - only look at immediate previous frame
		if frame_idx > 0:
			prev_frame = bowler.frames[frame_idx - 1]
			if prev_frame.is_strike and ball_idx < 2:
				return True
			elif prev_frame.is_spare and ball_idx == 0:
				return True
		
		return False
	
	def _get_strike_bonus_balls_for_display_fast(self, bowler, frame_idx):
		"""PERFORMANCE: Fast strike bonus balls retrieval"""
		bonus_balls = []
		balls_found = 0
		
		# PERFORMANCE: Only look ahead 2 frames maximum
		for j in range(frame_idx + 1, min(frame_idx + 3, len(bowler.frames))):
			if bowler.frames[j].balls and balls_found < 2:
				for ball in bowler.frames[j].balls:
					if balls_found < 2:
						bonus_balls.append(ball)
						balls_found += 1
					if balls_found >= 2:
						break
			if balls_found >= 2:
				break
		
		return bonus_balls
	
	def _get_spare_bonus_ball_for_display_fast(self, bowler, frame_idx):
		"""PERFORMANCE: Fast spare bonus ball retrieval"""
		# PERFORMANCE: Only look at next frame
		if frame_idx + 1 < len(bowler.frames):
			next_frame = bowler.frames[frame_idx + 1]
			if next_frame.balls:
				return next_frame.balls[0]
		return None
	
	def _is_strike_in_active_streak_fast(self, bowler, frame_idx):
		"""PERFORMANCE: Fast strike streak check"""
		if frame_idx >= 9:  # 10th frame - always show total
			return False
		
		# PERFORMANCE: Simple check - only look at next frame
		if frame_idx + 1 < len(bowler.frames):
			next_frame = bowler.frames[frame_idx + 1]
			return not next_frame.balls or next_frame.is_strike
		
		return True  # No next frame yet, so streak is active

	def _update_bowler_data(self, current_bowler_index):
		"""Update the frame display with current bowler data including bonus balls in frames."""
		
		logger.info(f"_update_bowler_data called with current_bowler_index = {current_bowler_index}")
		
		for bowler_idx, bowler in enumerate(self.bowlers):
			# Highlight current bowler (only if they haven't completed their game)
			if bowler_idx < len(self.bowler_name_labels):
				if bowler_idx == current_bowler_index and not getattr(bowler, 'game_completed', False):
					self.bowler_name_labels[bowler_idx].config(bg="yellow", fg="black")
				elif getattr(bowler, 'game_completed', False):
					# Show completed bowlers in a different color
					self.bowler_name_labels[bowler_idx].config(bg="green", fg="white")
				else:
					self.bowler_name_labels[bowler_idx].config(
						bg=self.settings.background_color,
						fg=self.settings.foreground_color
					)
			
			# Update frame displays for this bowler
			for frame_idx in range(len(bowler.frames)):
				# Skip if frame index is out of range
				if bowler_idx >= len(self.ball_labels) or frame_idx >= len(self.ball_labels[bowler_idx]):
					continue
				
				# Get the frame object
				frame = bowler.frames[frame_idx]
				
				# Display ball results with bonus balls shown in the earning frame
				ball_display_text = ""
				
				if hasattr(frame, 'balls') and frame.balls:
					display_parts = []
					is_tenth_frame = (frame_idx == 9)
					
					# Add the balls that were actually thrown in this frame
					for ball_idx, ball in enumerate(frame.balls):
						symbol_text = ball.symbol
						
						# Add bonus indicator if this ball was used as bonus for previous frame
						if self._ball_used_as_bonus(bowler, frame_idx, ball_idx):
							symbol_text += "*"
							
						display_parts.append(symbol_text)
					
					# NEW: Add bonus balls earned by this frame (if enabled)
					if getattr(self.settings, 'show_bonus_in_frame', True) and len(frame.balls) > 0:
						if frame.is_strike and not is_tenth_frame:
							# Get next 2 balls for strike bonus
							bonus_balls = self._get_strike_bonus_balls_for_display(bowler, frame_idx)
							for bonus_ball in bonus_balls:
								display_parts.append(bonus_ball.symbol)
						elif frame.is_spare and not is_tenth_frame:
							# Get next 1 ball for spare bonus
							bonus_ball = self._get_spare_bonus_ball_for_display(bowler, frame_idx)
							if bonus_ball:
								display_parts.append(bonus_ball.symbol)
					
					ball_display_text = " ".join(display_parts)
				
				# Set the display text
				self.ball_labels[bowler_idx][frame_idx].config(text=ball_display_text)
				
				# Frame total with strike streak handling
				total_display = ""
				if hasattr(frame, 'total') and frame.total > 0:
					if getattr(self.settings, 'strike_streak_mode', False) and frame.is_strike:
						# Check if this strike is part of an ongoing streak
						if self._is_strike_in_active_streak(bowler, frame_idx):
							total_display = "X"  # Don't show total until streak breaks
						else:
							total_display = str(frame.total)
					else:
						total_display = str(frame.total)
						
				self.total_labels[bowler_idx][frame_idx].config(text=total_display)
			
			# Update bowler's total score
			if bowler_idx < len(self.bowler_total_labels) and hasattr(bowler, 'total_score'):
				self.bowler_total_labels[bowler_idx].config(text=str(bowler.total_score))
			
	def _get_next_balls(self, bowler: Bowler, frame_idx: int, count: int) -> List[BallResult]:
		"""Get the next 'count' balls after the specified frame."""
		next_balls = []
		for j in range(frame_idx + 1, len(bowler.frames)):
			if bowler.frames[j].balls:
				next_balls.extend(bowler.frames[j].balls)
				if len(next_balls) >= count:
					break
					
		return next_balls[:count]	
	
	def _calculate_cumulative_score(self, bowler: Bowler, frame_idx: int) -> int:
		"""Calculate the cumulative score up to and including the specified frame."""
		cumulative_score = 0
		
		for i in range(frame_idx + 1):
			frame = bowler.frames[i]
			cumulative_score += frame.total
		
		return cumulative_score
		
	def enable_buttons(self, enabled=True):
		"""Enable or disable all game control buttons"""
		state = "normal" if enabled else "disabled"
		if self.hold_button:
			self.hold_button["state"] = state
		if self.skip_button:
			self.skip_button["state"] = state
		if self.reset_button:
			self.reset_button["state"] = state
		if self.settings_button:
			self.settings_button["state"] = state
			
	def create_timer(self, container, seconds, text_format="Time: {}s", bg_color=None, fg_color="red", font=("Arial", 16)):
		"""Create and return a timer label"""
		if bg_color is None:
			bg_color = self.settings.background_color
			
		timer_label = tk.Label(
			container,
			text=text_format.format(seconds),
			bg=bg_color,
			fg=fg_color,
			font=font
		)
		timer_label.pack()
		return timer_label
		
	def create_next_game_button(self, command, container=None):
		"""Create a next game button and return both the button and its container"""
		if container is None:
			container = self.button_container
			
		next_game_container = tk.Frame(container, bg=self.settings.background_color)
		next_game_container.pack(fill=tk.X, pady=5)
		
		next_game_button = tk.Button(
			next_game_container,
			text="NEXT GAME",
			bg="orange",
			fg="white",
			command=command,
			font=("Arial", 20)
		)
		next_game_button.pack(side=tk.LEFT, padx=5, pady=5, expand=True)
		
		# Return both the button and its container
		return next_game_button, next_game_container
	
	def _ball_used_as_bonus(self, bowler: Bowler, frame_idx: int, ball_idx: int) -> bool:
		"""Check if a specific ball was used as bonus for a previous frame."""
		# Check previous frames for strikes and spares that would use this ball as bonus
		for prev_frame_idx in range(frame_idx):
			prev_frame = bowler.frames[prev_frame_idx]
			
			# Strike bonus uses next 2 balls
			if hasattr(prev_frame, 'is_strike') and prev_frame.is_strike:
				next_balls_needed = 2
				balls_found = 0
				
				# Count balls from frames after the strike
				for check_frame_idx in range(prev_frame_idx + 1, len(bowler.frames)):
					check_frame = bowler.frames[check_frame_idx]
					for check_ball_idx, ball in enumerate(check_frame.balls):
						if check_frame_idx == frame_idx and check_ball_idx == ball_idx:
							return balls_found < next_balls_needed
						balls_found += 1
						if balls_found >= next_balls_needed:
							break
					if balls_found >= next_balls_needed:
						break
			
			# Spare bonus uses next 1 ball
			elif hasattr(prev_frame, 'is_spare') and prev_frame.is_spare:
				# Find the first ball after the spare
				for check_frame_idx in range(prev_frame_idx + 1, len(bowler.frames)):
					check_frame = bowler.frames[check_frame_idx]
					if check_frame.balls:
						if check_frame_idx == frame_idx and ball_idx == 0:
							return True
						break
		
		return False
	
	def _calculate_all_scores(self, bowler: Bowler):
		"""Calculate all frame scores with bonuses and make totals cumulative."""
		running_total = 0
		
		for i, frame in enumerate(bowler.frames):
			if not frame.balls:
				continue
			
			# Calculate frame value with bonus
			base_value = sum(b.value for b in frame.balls)
			bonus = 0
			
			# Recalculate strike/spare status
			if len(frame.balls) >= 1:
				frame.is_strike = (frame.balls[0].value == 15)
			
			if len(frame.balls) >= 2 and not frame.is_strike:
				first_two_value = frame.balls[0].value + frame.balls[1].value
				frame.is_spare = (first_two_value == 15)
			
			# Calculate bonuses and store bonus details for database
			if frame.is_strike:
				bonus = self._calculate_strike_bonus_across_bowlers(bowler, i)
				# Store bonus balls for database
				frame.bonus_balls = self._get_bonus_balls_for_db(bowler, i, 'strike')
			elif frame.is_spare:
				bonus = self._calculate_spare_bonus_across_bowlers(bowler, i)
				# Store bonus balls for database
				frame.bonus_balls = self._get_bonus_balls_for_db(bowler, i, 'spare')
			else:
				# No bonus for open frames
				frame.bonus_balls = []
				
			frame_score = base_value + bonus
			running_total += frame_score
			frame.total = running_total
			
			# Store breakdown for display
			frame.base_score = base_value
			frame.bonus_score = bonus
			
			logger.info(f"Frame {i+1}: base={base_value}, bonus={bonus}, frame_score={frame_score}, cumulative={running_total}")
		
		bowler.total_score = running_total
		logger.info(f"Bowler {bowler.name} total score: {running_total}")
	
	def _get_bonus_balls_for_db(self, bowler: Bowler, frame_idx: int, bonus_type: str) -> List[Dict]:
		"""Get bonus balls used for a strike or spare frame for database storage."""
		bonus_balls = []
		
		if bonus_type == 'strike':
			# Strike uses next 2 balls
			balls_found = 0
			for j in range(frame_idx + 1, len(bowler.frames)):
				if bowler.frames[j].balls:
					for ball in bowler.frames[j].balls:
						if balls_found < 2:
							bonus_balls.append({
								"frame": j + 1,
								"ball": balls_found + 1,
								"pin_config": ball.pin_config,
								"symbol": ball.symbol,
								"value": ball.value
							})
							balls_found += 1
						if balls_found >= 2:
							break
				if balls_found >= 2:
					break
					
		elif bonus_type == 'spare':
			# Spare uses next 1 ball
			for j in range(frame_idx + 1, len(bowler.frames)):
				if bowler.frames[j].balls:
					ball = bowler.frames[j].balls[0]
					bonus_balls.append({
						"frame": j + 1,
						"ball": 1,
						"pin_config": ball.pin_config,
						"symbol": ball.symbol,
						"value": ball.value
					})
					break
		
		return bonus_balls
	
	def _get_strike_bonus_balls_for_display(self, bowler: Bowler, frame_idx: int) -> List[BallResult]:
		"""Get the next 2 balls used as bonus for a strike frame for display purposes."""
		bonus_balls = []
		balls_found = 0
		
		for j in range(frame_idx + 1, len(bowler.frames)):
			if bowler.frames[j].balls and balls_found < 2:
				for ball in bowler.frames[j].balls:
					if balls_found < 2:
						bonus_balls.append(ball)
						balls_found += 1
					if balls_found >= 2:
						break
			if balls_found >= 2:
				break
		
		return bonus_balls

	def _get_spare_bonus_ball_for_display(self, bowler: Bowler, frame_idx: int) -> Optional[BallResult]:
		"""Get the next 1 ball used as bonus for a spare frame for display purposes."""
		for j in range(frame_idx + 1, len(bowler.frames)):
			if bowler.frames[j].balls:
				return bowler.frames[j].balls[0]
		return None

	def _is_strike_in_active_streak(self, bowler: Bowler, frame_idx: int) -> bool:
		"""Check if a strike is part of an active streak."""
		if frame_idx >= 9:  # 10th frame - always show total
			return False
		
		next_frame = bowler.frames[frame_idx + 1]
		
		# If next frame has no balls yet, this strike is in an active streak
		if not next_frame.balls:
			return True
		
		# If next frame is also a strike, this strike is in an active streak
		if next_frame.is_strike:
			return True
		
		return False
	
	def _open_test_simulator(self):
		"""Open the test simulator window"""
		from test_ball_simulator import TestBallSimulator
		
		if hasattr(self, 'parent') and self.parent:
			game = self.parent
			
			if not hasattr(game, 'test_simulator') or not game.test_simulator:
				game.test_simulator = TestBallSimulator(game, game.frame)
			
			game.test_simulator.open_simulator_window()
	
		
class SymbolManager:
	def __init__(self, settings: GameSettings):
		self.settings = settings
		self.patterns = settings.patterns
		self.pin_values = settings.pin_values
		
		# Future enhancement: Pre-load images/videos here
		self.symbol_media = {}
		self.popup_window = None
		
		logger.info("SymbolManager initialized with patterns from game settings")
	
	def determine_symbol(self, pin_result, ball_value, frame, ball_number=None):
		"""FIXED: Improved symbol determination with better spare detection."""
		if ball_number is None:
			ball_number = len(frame.balls)
		
		symbol = None
		
		if ball_number == 0:  # First ball ONLY
			if ball_value == 15:  # Strike (all pins down)
				symbol = 'X'
			elif ball_value == 0:  # No pins knocked down
				symbol = '-'
			else:
				# Use pin changes directly for pattern matching
				pin_config_str = ''.join(str(pin) for pin in pin_result)
				symbol = self.patterns.get(pin_config_str, str(ball_value))
		
		elif ball_number == 1:  # Second ball
			first_ball_value = frame.balls[0].value
			potential_total = first_ball_value + ball_value
			
			# CRITICAL: Only check for spare if first ball was NOT a strike
			if first_ball_value < 15 and potential_total == 15:  # Spare
				symbol = '/'
				logger.info(f"SPARE DETECTED: first_ball={first_ball_value} + second_ball={ball_value} = {potential_total}")
				# ENSURE frame status is updated immediately
				frame.is_spare = True
				frame.is_strike = False
			elif ball_value == 0:
				symbol = '-'
			else:
				# NO PATTERN MATCHING on second ball - just use numeric value
				symbol = str(ball_value)
		
		elif ball_number == 2:  # Third ball
			# In 10th frame, check for strikes on third ball
			if len(frame.balls) >= 2 and frame.balls[0].value + frame.balls[1].value == 15:
				# This is a third ball after a spare in 10th frame - can use patterns
				if ball_value == 15:  # Strike on third ball
					symbol = 'X'
				elif ball_value == 0:
					symbol = '-'
				else:
					# Check for pattern on third ball in 10th frame after spare
					pin_config_str = ''.join(str(pin) for pin in pin_result)
					symbol = self.patterns.get(pin_config_str, str(ball_value))
			elif len(frame.balls) >= 1 and frame.balls[0].value == 15:
				# This is a third ball after a strike in 10th frame - can use patterns  
				if ball_value == 15:  # Strike on third ball
					symbol = 'X'
				elif ball_value == 0:
					symbol = '-'
				else:
					# Check for pattern on third ball in 10th frame after strike
					pin_config_str = ''.join(str(pin) for pin in pin_result)
					symbol = self.patterns.get(pin_config_str, str(ball_value))
			else:
				# Regular frame third ball OR 10th frame third ball after open frame
				# NO PATTERN MATCHING - just use numeric value
				if ball_value == 0:
					symbol = '-'
				else:
					symbol = str(ball_value)
		
		# Final fallback
		if symbol is None:
			symbol = str(ball_value) if ball_value > 0 else '-'
		
		return symbol
	
	def should_show_popup(self, symbol, ball_number, frame):
		# Only show popup for first ball OR spare situations
		if ball_number == 0:
			# First ball - show popup for significant patterns
			if symbol == 'X':  # Strike - always show
				return True
			# For other first-ball patterns, only show significant ones
			if symbol and symbol not in ['-', '0'] and not symbol.isdigit():
				return True
		
		elif ball_number == 1:
			# Second ball - check for spare
			if symbol == '/':  # Spare
				return True
		
		# Third ball or later - no popup
		return False
	
	def show_symbol_popup(self, symbol, parent_window=None):
		"""
		Show symbol popup. Future enhancement: support images/videos.
		"""
		if not parent_window:
			logger.warning("No parent window provided for symbol popup")
			return
		
		try:
			# Use existing SymbolPopup if available
			if not hasattr(self, 'symbol_popup'):
				popup_settings = {
					'background_color': self.settings.background_color,
					'foreground_color': self.settings.foreground_color,
					'symbol_color': 'yellow'
				}
				self.symbol_popup = SymbolPopup(
					parent_window=parent_window,
					settings=popup_settings
				)
			
			# Show the popup
			self.symbol_popup.show_symbol(symbol, None)  # No machine instance needed
			logger.info(f"SYMBOL_POPUP: Displayed symbol '{symbol}'")
			
		except Exception as e:
			logger.error(f"Error showing symbol popup: {e}")
	
	def preload_media(self):
		# TODO: Load images/videos for each symbol
		# self.symbol_media['X'] = load_image('strike.png')
		# self.symbol_media['/'] = load_video('spare.mp4')
		pass
	
	def cleanup(self):
		"""Clean up resources."""
		if hasattr(self, 'symbol_popup'):
			del self.symbol_popup



class BaseGame:
	def __init__(self):
		self.game_started = False  # Track if the game is active
		self.frame = None  # Placeholder for the UI frame

	def start(self):
		"""Start the game."""
		self.game_started = True

	def process_ball(self, result: List[int]):
		process_start_time = time.time()
		logger.info(f"SCORING_START: Processing ball result: {result}")
		
		if not self.game_started or self.hold_active:
			logger.info("Game not active or on hold")
			return

		bowler = self.bowlers[self.current_bowler_index]
		frame = bowler.frames[bowler.current_frame]

		# CRITICAL: Pass game context to machine for last ball detection
		if hasattr(self.parent, 'machine'):
			self.parent.machine.game_context = self
		
		# Check if we need to complete a frame and move on
		if len(frame.balls) >= 3:
			logger.info(f"Frame {bowler.current_frame+1} already has {len(frame.balls)} balls - triggering frame completion")
			
			if bowler.current_frame < 9:
				self._advance_frame(bowler)
			else:
				self._end_bowler_game(bowler)
				
			# Schedule immediate full reset for frame completion
			logger.info("FRAME_COMPLETE_RESET: Scheduling immediate full reset")
			self._schedule_immediate_full_reset('frame_complete')
			self.update_ui()
			return

		# Ball-only calculation for 2nd and 3rd balls
		actual_ball_result = result.copy()
		logger.info(f"Results from Machine: {actual_ball_result}")
		
		if len(frame.balls) >= 1:
			# Get cumulative pins down from ALL previous balls in this frame
			cumulative_pins_down = [0, 0, 0, 0, 0]
			for ball in frame.balls:
				for i, pin in enumerate(ball.pin_config):
					if pin == 1:
						cumulative_pins_down[i] = 1
			
			# Calculate what THIS ball actually knocked down
			ball_only_result = [0, 0, 0, 0, 0]
			for i, pin in enumerate(result):
				if pin == 1 and cumulative_pins_down[i] == 0:
					ball_only_result[i] = 1
			
			actual_ball_result = ball_only_result
			logger.info("SCORING_BALL_ONLY: Ball-only calculation")
			logger.info(f"Machine reported: {result}, Ball-only: {ball_only_result}")

		# Calculate the ball value using ball-only result
		ball_value = sum(a * b for a, b in zip(actual_ball_result, self.settings.pin_values))
		
		# USE SYMBOL MANAGER for symbol determination
		ball_number = len(frame.balls)
		symbol = self.symbol_manager.determine_symbol(actual_ball_result, ball_value, frame, ball_number)
		
		logger.info(f"SCORING_SYMBOL: Determined symbol '{symbol}' (value: {ball_value})")
		
		# SHOW SYMBOL POPUP using SymbolManager
		if self.symbol_manager.should_show_popup(symbol, len(frame.balls), frame):
			parent_window = self.parent if hasattr(self, 'parent') else self.frame
			self.symbol_manager.show_symbol_popup(symbol, parent_window)
		
		# Create ball result
		ball_result = BallResult(pin_config=result, symbol=symbol, value=ball_value)
		frame.balls.append(ball_result)
		
		# Frame completion logic with EARLY reset scheduling
		frame_complete = False
		needs_frame_advance = False
		
		# Check for strike on any ball
		if ball_result.value == 15:  # Strike
			frame.is_strike = True
			logger.info("SCORING_STRIKE: Strike detected")
			
			if bowler.current_frame < 9:  # Not 10th frame
				needs_frame_advance = True
				frame_complete = True
			# 10th frame strikes never complete the frame after just 1 ball
			
		elif len(frame.balls) == 2:
			first_two_total = sum(ball.value for ball in frame.balls)
			if first_two_total == 15:  # Spare
				frame.is_spare = True
				logger.info("SCORING_SPARE: Spare detected")
				
				if bowler.current_frame < 9:  # Not 10th frame
					needs_frame_advance = True
					frame_complete = True
				# 10th frame spares never complete the frame after just 2 balls
				
			else:  # Open frame (no strike, no spare)
				if bowler.current_frame < 9:  # Not 10th frame
					needs_frame_advance = True
					frame_complete = True
				else:  # 10th frame open frame - NOW it's complete
					logger.info("SCORING_10TH_OPEN_COMPLETE: 10th frame complete (open frame)")
					frame_complete = True
		
		elif len(frame.balls) == 3:
			# ANY frame with 3 balls is complete
			if bowler.current_frame < 9:
				needs_frame_advance = True
				frame_complete = True
			else:  # 10th frame with 3 balls - always complete
				logger.info("SCORING_10TH_3BALLS_COMPLETE: 10th frame complete with 3 balls")
				frame_complete = True
		# Calculate scores
		self._calculate_all_scores(bowler)
		
		# Handle frame advancement and resets EARLY
		if needs_frame_advance:
			logger.info("SCORING_ADVANCE: Advancing frame and scheduling immediate reset")
			self._advance_frame(bowler)
			
			# Schedule immediate full reset for next frame/bowler
			logger.info("SCHEDULING_IMMEDIATE_RESET: Frame advance - scheduling immediate full reset")
			self._schedule_immediate_full_reset('frame_advance')
		
		elif frame_complete and bowler.current_frame == 9:
			# 10th frame complete
			logger.info("SCORING_10TH_COMPLETE: 10th frame complete")
			self._end_bowler_game(bowler)
			
			# Schedule immediate full reset for next bowler
			self._schedule_immediate_full_reset('bowler_complete')
		
		# Update UI
		self.update_ui()
		
		logger.info(f"SCORING_COMPLETE: Processed in {time.time() - process_start_time:.3f}s")
	def is_game_active(self):
		"""Check if the game is currently active."""
		return self.game_started

	def update_ui(self):
		"""Update the UI. To be implemented by subclasses."""
		raise NotImplementedError("Subclasses must implement update_ui")
		
	def handle_bowler_turn(self, bowler_name, result):
		"""Send the bowler's result to the server."""
		# TODO: Send game_data to the server and confirm receipt
		pass
	
# Configuration class for display options
# TODO: Update with other game types for display options to reduce code structure required
class DisplayConfig:
	"""Configuration options for display modes."""
	
	def __init__(self):
		self.show_bonus_asterisk = True	  # Show * after bonus balls
		self.show_frame_breakdown = False	# Show (15+8) in frame totals
		self.use_enhanced_tracking = False   # Use enhanced ball tracking system
		self.display_mode = "standard"	  # "standard", "detailed", or "simulation"
	
	def set_standard_mode(self):
		"""Standard display mode - current system."""
		self.show_bonus_asterisk = True
		self.show_frame_breakdown = False
		self.use_enhanced_tracking = False
		self.display_mode = "standard"
	
	def set_detailed_mode(self):
		"""Detailed mode - shows breakdowns."""
		self.show_bonus_asterisk = True
		self.show_frame_breakdown = True
		self.use_enhanced_tracking = False
		self.display_mode = "standard"
	
	def set_simulation_mode(self):
		"""Simulation mode - enhanced tracking for replay."""
		self.show_bonus_asterisk = False
		self.show_frame_breakdown = False
		self.use_enhanced_tracking = True
		self.display_mode = "simulation"

class PracticeGame(BaseGame):
	def __init__(self, settings: GameSettings, parent=None):
		super().__init__()
		self.settings = settings
		self.parent = parent
		self.frame = tk.Frame(self.parent, bg=self.settings.background_color)
		self.frame.pack(fill=tk.BOTH, expand=True)
		
		# Practice-specific settings - FIX: Use direct minutes or convert properly
		if hasattr(settings, 'practice_minutes'):
			self.practice_time_minutes = settings.practice_minutes
		else:
			# FIX: Check if total_time is already in minutes (> 10) or needs conversion
			time_value = settings.total_time or 1
			if time_value > 10:  # Already in minutes
				self.practice_time_minutes = time_value
			else:  # In blocks, convert to minutes
				self.practice_time_minutes = time_value * 30
		
		self.practice_start_time = None
		self.practice_end_time = None
		self.practice_timer_label = None
		self.game_started = False
		self.hold_active = False
		
		# UI elements
		self.practice_container = None
		self.control_buttons = None
		
		logger.info(f"PracticeGame initialized with {self.practice_time_minutes} minutes")
	
	def start(self):
		"""Start the practice mode"""
		self.game_started = True
		self.practice_start_time = time.time()
		self.practice_end_time = self.practice_start_time + (self.practice_time_minutes * 60)
		
		logger.info(f"Starting practice mode for {self.practice_time_minutes} minutes")
		
		# Create practice UI
		self._create_practice_ui()
		
		# Start timer updates
		self._update_practice_timer()
		
		# Activate ball detector for practice
		if hasattr(self.parent, 'setup_ball_detector'):
			# Create a minimal game context for ball detection
			self._setup_practice_ball_detection()
		
		# Update parent displays
		if hasattr(self.parent, 'set_game_display'):
			self.parent.set_game_display("Practice Mode")
		
		if hasattr(self.parent, 'set_info_label'):
			self.parent.set_info_label(f"Practice Time: {self.practice_time_minutes} min")
		
		if hasattr(self.parent, 'set_scroll_message'):
			self.parent.set_scroll_message("Practice mode active - Bowl freely to warm up!")
		
		# Update lane status
		if hasattr(self.parent, 'update_lane_status'):
			self.parent.update_lane_status("practice")
	
	def _create_practice_ui(self):
		"""Create the practice mode user interface"""
		# Clear any existing widgets
		for widget in self.frame.winfo_children():
			widget.destroy()
		
		self.practice_container = tk.Frame(self.frame, bg=self.settings.background_color)
		self.practice_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
		
		# Practice header
		title_label = tk.Label(
			self.practice_container,
			text="PRACTICE MODE",
			bg=self.settings.background_color,
			fg="yellow",
			font=("Arial", 48, "bold")
		)
		title_label.pack(pady=(50, 30))
		
		# Timer display
		self.practice_timer_label = tk.Label(
			self.practice_container,
			text=self._format_time_remaining(),
			bg=self.settings.background_color,
			fg="white",
			font=("Arial", 32)
		)
		self.practice_timer_label.pack(pady=20)
		
		# Instructions
		instructions = tk.Label(
			self.practice_container,
			text="Bowl freely to warm up!\nYour practice time will end automatically\nor when a new game is started.",
			bg=self.settings.background_color,
			fg=self.settings.foreground_color,
			font=("Arial", 18),
			justify=tk.CENTER
		)
		instructions.pack(pady=30)
		
		# Control buttons
		self._create_control_buttons()
	
	def _create_control_buttons(self):
		"""Create control buttons for practice mode"""
		self.control_buttons = tk.Frame(self.practice_container, bg=self.settings.background_color)
		self.control_buttons.pack(side=tk.BOTTOM, pady=30)
		
		# Reset pins button
		reset_btn = tk.Button(
			self.control_buttons,
			text="RESET PINS",
			bg="green",
			fg="white",
			command=self.reset_pins,
			font=("Arial", 20),
			width=15,
			height=2
		)
		reset_btn.pack(side=tk.LEFT, padx=10)
		
		# Hold button
		hold_btn = tk.Button(
			self.control_buttons,
			text="HOLD" if not self.hold_active else "RESUME",
			bg="red" if not self.hold_active else "green",
			fg="white",
			command=self.toggle_hold,
			font=("Arial", 20),
			width=15,
			height=2
		)
		hold_btn.pack(side=tk.LEFT, padx=10)
		
		# End practice button
		end_btn = tk.Button(
			self.control_buttons,
			text="END PRACTICE",
			bg="orange",
			fg="white",
			command=self.end_practice,
			font=("Arial", 20),
			width=15,
			height=2
		)
		end_btn.pack(side=tk.LEFT, padx=10)
	
	def _setup_practice_ball_detection(self):
		"""Setup ball detection for practice mode"""
		try:
			# Create a minimal game-like object for ball detection
			class PracticeBallHandler:
				def __init__(self, practice_game):
					self.practice_game = practice_game
					self.game_started = True
					self._hold_active = False
				
				def process_ball(self, result):
					if not self._hold_active:
						# Just log the ball for practice
						logger.info(f"Practice ball detected: {result}")
						# Show symbol popup if available
						ball_value = sum(a * b for a, b in zip(result, [2, 3, 5, 3, 2]))
						if ball_value == 15:
							symbol = 'X'  # Strike
						elif ball_value == 0:
							symbol = '-'  # Miss
						else:
							symbol = str(ball_value)
						
						# Show popup if machine has callback
						if hasattr(self.practice_game.parent, 'machine') and \
						   hasattr(self.practice_game.parent.machine, 'symbol_popup_callback') and \
						   self.practice_game.parent.machine.symbol_popup_callback:
							self.practice_game.parent.machine.symbol_popup_callback(symbol)
				
				@property
				def hold_active(self):
					return self._hold_active
				
				@hold_active.setter
				def hold_active(self, value):
					self._hold_active = value
				
				def is_game_active(self):
					return self.practice_game.game_started and not self._hold_active
			
			# Set up ball detector with practice handler
			if hasattr(self.parent, 'machine'):
				self.ball_handler = PracticeBallHandler(self)
				
				# Create or update ball detector
				if not hasattr(self.parent, 'ball_detector') or not self.parent.ball_detector:
					from active_ball_detector import ActiveBallDetector
					self.parent.ball_detector = ActiveBallDetector(self.ball_handler, self.parent.machine)
					logger.info("Created new ball detector for practice")
				else:
					# Update existing ball detector
					self.parent.ball_detector.game = self.ball_handler
					# Ensure it's not suspended
					if hasattr(self.parent.ball_detector, 'set_suspended'):
						self.parent.ball_detector.set_suspended(False)
					logger.info("Updated existing ball detector for practice")
				
				logger.info("Practice ball detection setup completed")
		
		except Exception as e:
			logger.error(f"Error setting up practice ball detection: {e}")
			# Continue without ball detection - practice can still work for pin resets
			logger.info("Practice mode will continue without ball detection")
	
	def _update_practice_timer(self):
		"""Update the practice timer display"""
		if not self.game_started:
			return
		
		current_time = time.time()
		
		# Check if practice time has expired
		if current_time >= self.practice_end_time:
			self._end_practice_time_expired()
			return
		
		# Update timer display
		if self.practice_timer_label:
			self.practice_timer_label.config(text=self._format_time_remaining())
		
		# Schedule next update
		self.frame.after(1000, self._update_practice_timer)
	
	def _format_time_remaining(self):
		"""Format the remaining time for display"""
		if not self.practice_end_time:
			return "Time Remaining: --:--"
		
		remaining_seconds = max(0, int(self.practice_end_time - time.time()))
		minutes = remaining_seconds // 60
		seconds = remaining_seconds % 60
		
		return f"Time Remaining: {minutes:02d}:{seconds:02d}"
	
	def _end_practice_time_expired(self):
		"""Handle practice time expiration"""
		logger.info("Practice time expired")
		self.game_started = False
		
		# Update UI to show time expired
		if self.practice_timer_label:
			self.practice_timer_label.config(text="Practice Time Expired", fg="red")
		
		# Update displays
		if hasattr(self.parent, 'set_scroll_message'):
			self.parent.set_scroll_message("Practice time has expired. Waiting for new game assignment.")
		
		# Could automatically transition to idle state or wait for new game
		self._transition_to_idle()
	
	def toggle_hold(self):
		"""Toggle hold state"""
		self.hold_active = not self.hold_active
		
		# Update button appearance
		for widget in self.control_buttons.winfo_children():
			if "HOLD" in widget['text'] or "RESUME" in widget['text']:
				widget.config(
					text="RESUME" if self.hold_active else "HOLD",
					bg="green" if self.hold_active else "red"
				)
		
		# Update lane status
		if hasattr(self.parent, 'update_lane_status'):
			status = "hold" if self.hold_active else "practice"
			self.parent.update_lane_status(status)
		
		logger.info(f"Practice mode {'held' if self.hold_active else 'resumed'}")
	
	def reset_pins(self):
		"""Reset pins during practice"""
		if hasattr(self.parent, 'machine'):
			logger.info("Practice mode: Resetting pins")
			self.parent.machine.reset_pins()
		else:
			logger.error("No machine available for pin reset")
	
	def end_practice(self):
		"""End practice mode manually"""
		logger.info("Practice mode ended manually")
		self.game_started = False
		
		# Clear ball detector reference
		if hasattr(self, 'ball_handler'):
			del self.ball_handler
		
		self._transition_to_idle()
	
	def cleanup(self):
		"""Clean up practice game resources"""
		logger.info("Cleaning up practice game")
		self.game_started = False
		
		# Clear timer
		if hasattr(self, 'practice_timer_label'):
			self.practice_timer_label = None
		
		# Clear ball detector reference
		if hasattr(self, 'ball_handler'):
			del self.ball_handler
		
		# REFINED: Clear all widgets from frame but don't destroy the frame itself
		if hasattr(self, 'frame') and self.frame:
			children_to_destroy = list(self.frame.winfo_children())
			for widget in children_to_destroy:
				try:
					if widget.winfo_exists():
						widget.destroy()
				except tk.TclError:
					pass
				except Exception:
					pass
			
			# Force update but keep the frame
			try:
				self.frame.update_idletasks()
			except Exception as e:
				logger.warning(f"Error updating frame after cleanup: {e}")
	
	def _transition_to_idle(self):
		"""Transition to idle state after practice"""
		# Clear the UI
		for widget in self.frame.winfo_children():
			widget.destroy()
		
		# Create idle screen
		self._create_idle_screen()
		
		# Update displays
		if hasattr(self.parent, 'set_game_display'):
			self.parent.set_game_display("Practice Complete")
		
		if hasattr(self.parent, 'update_lane_status'):
			self.parent.update_lane_status("idle")
	
	def _create_idle_screen(self):
		"""Create idle screen after practice"""
		idle_container = tk.Frame(self.frame, bg=self.settings.background_color)
		idle_container.pack(fill=tk.BOTH, expand=True, padx=50, pady=50)
		
		# Title
		title_label = tk.Label(
			idle_container,
			text="PRACTICE COMPLETE",
			bg=self.settings.background_color,
			fg="green",
			font=("Arial", 36, "bold")
		)
		title_label.pack(pady=(50, 30))
		
		# Status
		status_label = tk.Label(
			idle_container,
			text="Ready for Game Assignment",
			bg=self.settings.background_color,
			fg=self.settings.foreground_color,
			font=("Arial", 24)
		)
		status_label.pack(pady=20)
	
	def handle_end_game_request(self, force_end=True, reason="Server request"):
		"""Handle end game request for practice mode"""
		logger.info(f"Practice mode received end game request: {reason}")
		self.game_started = False
		self._transition_to_idle()
	
	def update_ui(self):
		"""Update UI (minimal for practice mode)"""
		pass  # Practice mode UI is static except for timer
	
	def is_game_active(self):
		"""Check if practice is active"""
		return self.game_started

class QuickGame(BaseGame):
	def __init__(self, bowlers: List[str], settings: GameSettings, parent=None):
		super().__init__()
		self.settings = settings
		
		# Ensure new settings have default values if not provided
		if not hasattr(self.settings, 'strike_streak_mode'):
			self.settings.strike_streak_mode = False
		if not hasattr(self.settings, 'show_bonus_in_frame'):
			self.settings.show_bonus_in_frame = True
		
		# Initialize bowlers with 10 empty frames
		self.bowlers = [
			Bowler(
				name=name,
				frames=[Frame(balls=[], total=0) for _ in range(10)]
			) for name in bowlers
		]
		
		self.parent = parent
		# Use the parent's game_window instead of creating a new frame
		if parent and hasattr(parent, 'game_window'):
			self.frame = parent.game_window
		else:
			self.frame = tk.Frame(parent, bg=self.settings.background_color)
			self.frame.pack(fill=tk.BOTH, expand=True)
		
		# Create SymbolManager with game settings
		self.symbol_manager = SymbolManager(self.settings)
		logger.info("SymbolManager created for QuickGame")
		
		# Create UI manager
		self.ui_manager = GameUIManager(self.frame, self.bowlers, self.settings, self)
		self.ui_manager.set_button_callbacks(
			on_reset=self.reset_pins,
			on_skip=self.skip_bowler,
			on_hold=self.toggle_hold,
			on_settings=self.open_settings,
			on_pin_restore=self.pin_restore
		)
		
		# Game state
		self.current_bowler_index = 0
		self.current_game_number = 1
		self.game_data = []
		self.hold_active = False
		self.game_started = False
		self.enable_bowler_reordering = False
		self.machine_status = None
		
		# Timer properties
		self.timer_running = False
		self.timer_seconds = 60
		self.timer_label = None
		self.next_game_button = None
		self.next_game_container = None
		self.next_game_countdown = None
		self.next_game_countdown_seconds = 60
		self.show_detail_var = False
		self.game_start_time = None
		self.total_game_time_minutes = None
		self.time_warning_shown = False

		# Calculate total game time in minutes (time setting × 30 minutes)
		if self.settings.total_time is not None:
			self.total_game_time_minutes = self.settings.total_time * 30  # 3 = 90 minutes
			logger.info(f"Game time limit set to {self.total_game_time_minutes} minutes ({self.settings.total_time} × 30min)")
		
		# Register a listener for machine status responses
		dispatcher.register_listener('machine_status_response', self._handle_machine_status)
		dispatcher.register_listener('request_machine_status', self._request_machine_status)
		dispatcher.register_listener('add_time_request', self.handle_add_time_request)
		
		self.pin_up_image = tk.PhotoImage(file="./5pin_up.png") # TODO: add back file="/home/centrebowl/Desktop/Bowling/
		self.pin_down_image = tk.PhotoImage(file="./5pin_down.png") # TODO: add back file="/home/centrebowl/Desktop/Bowling/
		
	def start(self):
		"""Start the quick game with proper time tracking."""
		logger.info(f"Starting Quick Game with {len(self.bowlers)} bowlers")
		if self.settings.total_games:
			logger.info(f"Number of games: {self.settings.total_games}")
		if self.settings.total_time:
			logger.info(f"Time allocation: {self.settings.total_time} × 30min = {self.total_game_time_minutes} minutes")
		if self.settings.pre_bowl:
			logger.info(f"Pre-bowl bowlers: {', '.join(self.settings.pre_bowl)}")
	
		# Start time tracking immediately
		self.game_started = True
		self.game_start_time = time.time()
		self.current_bowler_index = 0
		
		# Start the game time monitoring
		if self.total_game_time_minutes is not None:
			self._start_time_monitoring()
		
		self.update_ui()
	
		# Update the game display to show the current bowler
		if hasattr(self, 'parent') and hasattr(self.parent, 'set_game_display'):
			self.parent.set_game_display(f"Current Bowler: {self.bowlers[self.current_bowler_index].name}")
			
		# Update initial time display
		self._update_time_display()
		
	def _start_time_monitoring(self):
		"""Start monitoring game time and updating displays."""
		if self.total_game_time_minutes is None:
			return
			
		logger.info(f"Starting time monitoring for {self.total_game_time_minutes} minute game")
		
		# Schedule the first time update in 1 second
		self.frame.after(1000, self._update_time_monitoring)
	
	def _update_time_monitoring(self):
		"""Update time displays and check for time warnings."""
		if not self.game_started or self.total_game_time_minutes is None:
			return
			
		# Calculate time remaining
		elapsed_seconds = time.time() - self.game_start_time
		elapsed_minutes = elapsed_seconds / 60
		remaining_minutes = self.total_game_time_minutes - elapsed_minutes
		
		# Update displays
		self._update_time_display()
		
		# Check for 10-minute warning
		if remaining_minutes <= 10 and not self.time_warning_shown:
			self.time_warning_shown = True
			warning_msg = f"Your game will be coming to an end in {int(remaining_minutes)} minutes.\n\nSee front desk to extend your time."
			if hasattr(self.parent, 'set_scroll_message'):
				dispatcher.listeners['scroll_message'][0]({warning_msg})
			logger.info("10-minute warning displayed")
		
		# Check if time is up
		if remaining_minutes <= 0:
			logger.info("Game time expired")
			self._handle_time_expiration()
			return
		
		# Schedule next update in 60 seconds (1 minute)
		self.frame.after(60000, self._update_time_monitoring)
	
	def _handle_time_expiration(self):
		"""Handle time expiration with different logic for 10th frame vs earlier frames."""
		logger.info("Handling time expiration")
		
		# Check if any bowler is currently in their 10th frame
		anyone_in_10th_frame = any(bowler.current_frame == 9 and len(bowler.frames[9].balls) > 0 
								  for bowler in self.bowlers if bowler.current_frame < 10)
		
		if anyone_in_10th_frame:
			# Someone is in 10th frame - allow them to finish
			logger.info("Time expired but bowlers are in 10th frame - allowing completion")
			self._show_10th_frame_completion_popup()
		else:
			# No one in 10th frame - show time expired popup with 10 min timer
			logger.info("Time expired - showing time expired popup with 10 min timer")
			self._show_time_expired_popup()
	
	def _show_10th_frame_completion_popup(self):
		"""Show popup allowing 10th frame completion."""
		popup = tk.Toplevel(self.frame)
		popup.title("Time Expired")
		popup.geometry("500x200")
		popup.configure(bg='red')
		popup.grab_set()  # Make modal
		
		# Center the popup
		popup.transient(self.frame)
		popup.update_idletasks()
		width = popup.winfo_width()
		height = popup.winfo_height()
		x = (popup.winfo_screenwidth() // 2) - (width // 2)
		y = (popup.winfo_screenheight() // 2) - (height // 2)
		popup.geometry(f'+{x}+{y}')
		
		# Message
		tk.Label(
			popup,
			text="Time has expired, see front desk to add more time.\n\nPress OK to finish 10th frame",
			bg='red',
			fg='white',
			font=("Arial", 14, "bold"),
			wraplength=450,
			justify=tk.CENTER
		).pack(expand=True, pady=20)
		
		# OK button
		def on_ok():
			popup.destroy()
			# Set flag to monitor for 10th frame completion
			self.allow_10th_frame_completion = True
			self._start_10th_frame_monitoring()
			
		tk.Button(
			popup,
			text="OK",
			bg="white",
			fg="red",
			command=on_ok,
			font=("Arial", 12, "bold"),
			width=10
		).pack(pady=10)
	
	def _start_10th_frame_monitoring(self):
		"""Monitor for 10th frame completion and start closing timer when done."""
		if not hasattr(self, 'allow_10th_frame_completion') or not self.allow_10th_frame_completion:
			return
		
		# Check if all bowlers have completed their 10th frames
		all_10th_complete = True
		for bowler in self.bowlers:
			if bowler.current_frame < 10:
				# Check if this bowler is in 10th frame and hasn't finished
				if bowler.current_frame == 9:
					# In 10th frame - check if they've finished
					frame = bowler.frames[9]
					if not self._is_10th_frame_complete(frame):
						all_10th_complete = False
						break
				else:
					# Not even in 10th frame yet
					all_10th_complete = False
					break
		
		if all_10th_complete:
			logger.info("All 10th frames completed after time expiration")
			self.allow_10th_frame_completion = False
			self._show_closing_game_popup()
		else:
			# Check again in 5 seconds
			self.frame.after(5000, self._start_10th_frame_monitoring)
			
	def _is_10th_frame_complete_after_this_ball(self, frame):
		"""Check if 10th frame is complete after this ball"""
		num_balls = len(frame.balls)
		
		return num_balls >= 3
	
	def _is_10th_frame_complete(self, frame):
		num_balls = len(frame.balls)
		
		if num_balls == 3:
			return True
		
		return False
	
	def _show_closing_game_popup(self):
		"""Show 5-minute closing game countdown popup."""
		popup = tk.Toplevel(self.frame)
		popup.title("Game Closing")
		popup.geometry("400x150")
		popup.configure(bg='orange')
		popup.grab_set()  # Make modal
		
		# Center the popup
		popup.transient(self.frame)
		popup.update_idletasks()
		width = popup.winfo_width()
		height = popup.winfo_height()
		x = (popup.winfo_screenwidth() // 2) - (width // 2)
		y = (popup.winfo_screenheight() // 2) - (height // 2)
		popup.geometry(f'+{x}+{y}')
		
		# Countdown label
		countdown_label = tk.Label(
			popup,
			text="Closing game in: 5:00",
			bg='orange',
			fg='white',
			font=("Arial", 16, "bold")
		)
		countdown_label.pack(expand=True)
		
		# Start 5-minute countdown
		self._start_closing_countdown(popup, countdown_label, 300)  # 5 minutes = 300 seconds
	
	def _show_time_expired_popup(self):
		"""Show time expired popup with 10-minute background timer."""
		popup = tk.Toplevel(self.frame)
		popup.title("Time Expired")
		popup.geometry("500x200")
		popup.configure(bg='red')
		popup.grab_set()  # Make modal
		
		# Center the popup
		popup.transient(self.frame)
		popup.update_idletasks()
		width = popup.winfo_width()
		height = popup.winfo_height()
		x = (popup.winfo_screenwidth() // 2) - (width // 2)
		y = (popup.winfo_screenheight() // 2) - (height // 2)
		popup.geometry(f'+{x}+{y}')
		
		# Message
		tk.Label(
			popup,
			text="Time has expired, see front desk to add more time.",
			bg='red',
			fg='white',
			font=("Arial", 14, "bold"),
			wraplength=450,
			justify=tk.CENTER
		).pack(expand=True, pady=20)
		
		# Countdown label
		countdown_label = tk.Label(
			popup,
			text="Auto-close in: 10:00",
			bg='red',
			fg='white',
			font=("Arial", 12)
		)
		countdown_label.pack(pady=10)
		
		# Close button
		def on_close():
			popup.destroy()
			# Continue background timer even if popup is closed
			
		tk.Button(
			popup,
			text="Close",
			bg="white",
			fg="red",
			command=on_close,
			font=("Arial", 12),
			width=10
		).pack(pady=10)
		
		# Start 10-minute countdown (background timer continues even if popup closed)
		self._start_background_timer(popup, countdown_label, 600)  # 10 minutes = 600 seconds
	
	def _start_closing_countdown(self, popup, label, seconds_remaining):
		"""Handle the 5-minute closing countdown."""
		if seconds_remaining <= 0:
			# Time up - close game
			try:
				popup.destroy()
			except:
				pass
			self._end_game_due_to_time()
			return
		
		# Update label
		minutes = seconds_remaining // 60
		seconds = seconds_remaining % 60
		try:
			label.config(text=f"Closing game in: {minutes}:{seconds:02d}")
		except:
			# Popup was closed
			pass
		
		# Schedule next update
		self.frame.after(1000, lambda: self._start_closing_countdown(popup, label, seconds_remaining - 1))
	
	def _start_background_timer(self, popup, label, seconds_remaining):
		"""Handle the 10-minute background timer that continues even if popup is closed."""
		if seconds_remaining <= 0:
			# Time up - close game
			try:
				popup.destroy()
			except:
				pass
			self._end_game_due_to_time()
			return
		
		# Update label if popup still exists
		minutes = seconds_remaining // 60
		seconds = seconds_remaining % 60
		try:
			if popup.winfo_exists():
				label.config(text=f"Auto-close in: {minutes}:{seconds:02d}")
		except:
			# Popup was closed - continue timer in background
			pass
		
		# Schedule next update (continues even if popup closed)
		self.frame.after(1000, lambda: self._start_background_timer(popup, label, seconds_remaining - 1))
	
	def _end_bowler_game(self, bowler: Bowler):
		"""End the game for the bowler and move to the next bowler."""
		# Store the current bowler index for reordering
		old_index = self.current_bowler_index
		
		# Calculate final score correctly - use the last frame's total (already cumulative)
		if bowler.frames and bowler.frames[-1].total > 0:
			bowler.total_score = bowler.frames[-1].total
		else:
			# Fallback: calculate total properly
			bowler.total_score = bowler.frames[9].total if len(bowler.frames) > 9 else 0
		
		# Add a property to mark bowler as completed rather than just relying on frame number
		bowler.game_completed = True
		
		# Set the current frame to 10 to mark this bowler as completed
		bowler.current_frame = 10
		
		logger.info(f"Bowler {bowler.name} completed game with score {bowler.total_score}")
		
		# This ensures the final score and frame are displayed
		logger.info("BOWLER_COMPLETE: Updating UI to show final results before proceeding")
		self.update_ui()
		
		# Check if all bowlers have completed their games
		all_complete = True
		for b in self.bowlers:
			if b.current_frame < 10:
				all_complete = False
				break
		
		if all_complete:
			# All bowlers have finished, end the game
			logger.info("All bowlers completed - ending game")
			self._end_game()
			return
		
		# Otherwise, move to next bowler who hasn't completed their game
		next_bowler_found = False
		for i in range(1, len(self.bowlers) + 1):
			next_idx = (self.current_bowler_index + i) % len(self.bowlers)
			next_b = self.bowlers[next_idx]
			
			# Check if the bowler has frames left to play
			if next_b.current_frame < 10:
				self.current_bowler_index = next_idx
				next_bowler_found = True
				break
		
		# If no bowler found with incomplete frames, end the game
		if not next_bowler_found:
			logger.info("No more active bowlers found - ending game")
			self._end_game()
			return
		
		# Reset pins
		if 'reset_pins' in dispatcher.listeners and dispatcher.listeners['reset_pins']:
			logger.info("Resetting pins for next bowler")
			self.reset_pins()
		
		# Display the current bowler's name in the UI
		current_bowler = self.bowlers[self.current_bowler_index].name
		if hasattr(self, 'parent') and hasattr(self.parent, 'set_game_display'):
			self.parent.set_game_display(f"Current Bowler: {current_bowler}")
		
		# Update the UI with explicit current bowler index
		logger.info(f"BOWLER_COMPLETE: Moving to next bowler {current_bowler} at index {self.current_bowler_index}")
		self.update_ui()
	
	def _end_game_due_to_time(self):
		"""End the game because time has expired."""
		logger.info("Ending game due to time expiration")
		
		# Update displays
		if hasattr(self.parent, 'set_game_display'):
			self.parent.set_game_display("TIME EXPIRED")
		
		if hasattr(self.parent, 'set_scroll_message'):
			dispatcher.listeners['scroll_message'][0]({"Game time has expired. Thank you for bowling!"})
		
		# Call the normal end game process
		self._end_game()
	
	def _update_time_display(self):
		"""Update the time display in the top bar."""
		if not self.game_started or self.total_game_time_minutes is None:
			return
			
		# Calculate remaining time
		elapsed_seconds = time.time() - self.game_start_time
		elapsed_minutes = elapsed_seconds / 60
		remaining_minutes = max(0, self.total_game_time_minutes - elapsed_minutes)
		
		# Round to nearest 5-minute increment for display
		display_minutes = max(0, int((remaining_minutes + 2.5) // 5) * 5)
		
		# Update info label with time remaining
		if hasattr(self.parent, 'set_info_label'):
			if display_minutes > 0:
				self.parent.set_info_label(f"Time Remaining: {display_minutes} min")
			else:
				self.parent.set_info_label("Time Expired")
	
	def is_game_active(self):
		"""Check if the game is currently active."""
		return self.game_started

	def skip_bowler(self):
		"""ENHANCED: Skip bowler with improved correction flag preservation."""
		logger.info(f"SKIP_REQUEST: Current game_started status: {self.game_started}")
		
		if not self.game_started:
			logger.warning("Game not started - skip ignored")
			return
		
		current_bowler = self.bowlers[self.current_bowler_index]
		
		# ENHANCED: Check for correction flags and log detailed info
		correction_info = None
		if hasattr(current_bowler, 'correction_flags'):
			current_frame_idx = current_bowler.current_frame
			if current_frame_idx in current_bowler.correction_flags:
				flag_info = current_bowler.correction_flags[current_frame_idx]
				if flag_info.get('needs_continuation', False):
					correction_info = flag_info
					logger.info(f"SKIP_WITH_CORRECTION: Preserving correction for {current_bowler.name} frame {current_frame_idx+1}")
					logger.info(f"Correction details: {flag_info}")
					
					# Ensure the flag persists through the skip
					flag_info['preserved_through_skip'] = True
					flag_info['skip_time'] = time.time()
		
		# Move to next bowler
		logger.info("Using _move_to_next_bowler to handle skip")
		self._move_to_next_bowler()
		
		# Show detailed message about correction flag preservation
		if correction_info and hasattr(self.parent, 'set_scroll_message'):
			reason = correction_info.get('reason', 'Frame correction')
			self.parent.set_scroll_message(f"Skipped {current_bowler.name} - {reason} will resume when they return")

	def toggle_hold(self):
		"""Toggle the HOLD state of the game."""
		self.hold_active = not self.hold_active
		if self.hold_active:
			logger.info("Game is on HOLD - Only settings and reset functions are available")
			
			# Update lane status to hold
			if hasattr(self.parent, 'update_lane_status'):
				self.parent.update_lane_status("hold")
		else:
			logger.info("Game is RESUMED")
			
			# Update lane status to active
			if hasattr(self.parent, 'update_lane_status'):
				self.parent.update_lane_status("active")
	
	def process_ball(self, result: List[int]):
		"""FIXED: Process ball with proper spare detection and frame completion logic"""
		process_start_time = time.time()
		logger.info(f"SCORING_START: Processing ball result: {result}")
		
		if not self.game_started or self.hold_active:
			logger.info("Game not active or on hold")
			return
	
		bowler = self.bowlers[self.current_bowler_index]
		frame = bowler.frames[bowler.current_frame]
	
		# CRITICAL: Pass game context to machine for last ball detection
		if hasattr(self.parent, 'machine'):
			self.parent.machine.game_context = self
		
		# Check if we need to complete a frame and move on
		if len(frame.balls) >= 3:
			logger.info(f"Frame {bowler.current_frame+1} already has {len(frame.balls)} balls - triggering frame completion")
			
			if bowler.current_frame < 9:
				self._advance_frame(bowler)
			else:
				self._end_bowler_game(bowler)
				
			# Schedule immediate full reset for frame completion
			logger.info("FRAME_COMPLETE_RESET: Scheduling immediate full reset")
			self._schedule_immediate_full_reset('frame_complete')
			self.update_ui()
			return
	
		# Ball-only calculation for 2nd and 3rd balls
		actual_ball_result = result.copy()
		logger.info(f"Results from Machine: {actual_ball_result}")
		
		if len(frame.balls) >= 1:
			# Get cumulative pins down from ALL previous balls in this frame
			cumulative_pins_down = [0, 0, 0, 0, 0]
			for ball in frame.balls:
				for i, pin in enumerate(ball.pin_config):
					if pin == 1:
						cumulative_pins_down[i] = 1
			
			# Calculate what THIS ball actually knocked down
			ball_only_result = [0, 0, 0, 0, 0]
			for i, pin in enumerate(result):
				if pin == 1 and cumulative_pins_down[i] == 0:
					ball_only_result[i] = 1
			
			actual_ball_result = ball_only_result
			logger.info("SCORING_BALL_ONLY: Ball-only calculation")
			logger.info(f"Machine reported: {result}, Ball-only: {ball_only_result}")
	
		# Calculate the ball value using ball-only result
		ball_value = sum(a * b for a, b in zip(actual_ball_result, self.settings.pin_values))
		
		# USE SYMBOL MANAGER for symbol determination
		ball_number = len(frame.balls)
		symbol = self.symbol_manager.determine_symbol(actual_ball_result, ball_value, frame, ball_number)
		
		logger.info(f"SCORING_SYMBOL: Determined symbol '{symbol}' (value: {ball_value})")
		
		# Create ball result
		ball_result = BallResult(pin_config=result, symbol=symbol, value=ball_value)
		frame.balls.append(ball_result)
		
		# FIXED: Frame completion logic with proper spare detection
		frame_complete = False
		needs_frame_advance = False
		
		# Check for strike on any ball
		if ball_result.value == 15:  # Strike
			frame.is_strike = True
			logger.info("SCORING_STRIKE: Strike detected")
			
			if bowler.current_frame < 9:  # Not 10th frame
				needs_frame_advance = True
				frame_complete = True
			# 10th frame strikes never complete the frame after just 1 ball
			
		elif len(frame.balls) == 2:
			# FIXED: Check for spare IMMEDIATELY after second ball
			first_ball_value = frame.balls[0].value
			second_ball_value = frame.balls[1].value
			total_value = first_ball_value + second_ball_value
			
			if total_value == 15 and first_ball_value < 15:  # Spare (not strike on first ball)
				frame.is_spare = True
				logger.info(f"SCORING_SPARE: Spare detected ({first_ball_value} + {second_ball_value} = 15)")
				
				if bowler.current_frame < 9:  # Not 10th frame
					needs_frame_advance = True
					frame_complete = True
				# 10th frame spares never complete the frame after just 2 balls
			else:
				# Not a spare - frame continues to third ball for regular frames
				if bowler.current_frame < 9:
					logger.info("CANADIAN_5PIN: Regular frame continues to third ball")
				else:
					# 10th frame open frame after 2 balls - complete if no strike/spare
					if first_ball_value < 15 and total_value < 15:
						logger.info("SCORING_10TH_OPEN_COMPLETE: 10th frame complete (open frame)")
						frame_complete = True
						needs_frame_advance = False
		
		elif len(frame.balls) == 3:
			# Third ball - ALWAYS completes frame
			if bowler.current_frame < 9:
				needs_frame_advance = True
				frame_complete = True
				logger.info("CANADIAN_5PIN: Regular frame complete after 3 balls")
			else:
				# 10th frame ALWAYS completes after 3rd ball
				logger.info("SCORING_10TH_3BALLS_COMPLETE: 10th frame complete with 3 balls")
				frame_complete = True
		
		# Calculate scores for all frames
		self._calculate_all_scores(bowler)
		
		# Handle frame advancement and resets EARLY
		if needs_frame_advance:
			logger.info("SCORING_ADVANCE: Advancing frame and scheduling immediate reset")
			self._advance_frame(bowler)
			
			# Schedule immediate full reset for next frame/bowler
			logger.info("SCHEDULING_IMMEDIATE_RESET: Frame advance - scheduling immediate full reset")
			self._schedule_immediate_full_reset('frame_advance')
		
		elif frame_complete and bowler.current_frame == 9:
			# 10th frame complete
			logger.info("SCORING_10TH_COMPLETE: 10th frame complete")
			self._end_bowler_game(bowler)
			
			# Schedule immediate full reset for next bowler
			self._schedule_immediate_full_reset('bowler_complete')
		
		# Update UI
		self.update_ui()
		
		logger.info(f"SCORING_COMPLETE: Processed in {time.time() - process_start_time:.3f}s")
	
	
	# Fix 2: Enhanced revert_last_ball with proper state restoration
	def _perform_revert_last_ball(self, target_bowler_idx, target_frame_idx, target_ball_idx, target_bowler, target_frame):
		"""FIXED: Perform revert with proper frame status recalculation"""
		logger.info(f"Enhanced revert: ball {target_ball_idx + 1} from {target_bowler.name}, frame {target_frame_idx + 1}")
		
		# Store original states for restoration
		original_bowler_idx = self.current_bowler_index
		
		# Calculate correct pin state after removing this ball
		pins_should_be = self._calculate_pin_state_after_revert(target_frame, target_ball_idx)
		
		# Remove the ball
		removed_ball = target_frame.balls.pop(target_ball_idx)
		logger.info(f"Removed ball: {removed_ball.symbol} (value: {removed_ball.value})")
		
		# CRITICAL: Recalculate frame status PROPERLY after ball removal
		self._recalculate_frame_status_after_revert_fixed(target_frame)
		
		# Determine correct game state after revert
		correct_state = self._determine_correct_game_state_after_revert(
			target_bowler_idx, target_frame_idx, target_ball_idx, target_bowler, target_frame
		)
		
		# Apply the correct game state
		self.current_bowler_index = correct_state['bowler_index']
		target_bowler.current_frame = correct_state['current_frame']
		
		# Recalculate all scores
		for bowler in self.bowlers:
			self._calculate_all_scores(bowler)
		
		# Handle machine state
		if hasattr(self.parent, 'machine'):
			if correct_state['needs_full_reset']:
				self.parent.machine._force_full_reset = True
				logger.info("REVERT: Set full reset flag")
			else:
				# Restore pins to calculated state
				logger.info(f"REVERT: Restoring pins to state: {pins_should_be}")
				if 'pin_set' in dispatcher.listeners and dispatcher.listeners['pin_set']:
					dispatcher.listeners['pin_set'][0](pins_should_be)
		
		# Update UI
		self.update_ui()
		
		# Update game display
		if hasattr(self, 'parent') and hasattr(self.parent, 'set_game_display'):
			current_bowler = self.bowlers[self.current_bowler_index]
			self.parent.set_game_display(f"Current Bowler: {current_bowler.name}")
		
		logger.info(f"Enhanced revert complete. Game state: Bowler {self.bowlers[self.current_bowler_index].name}, Frame {self.bowlers[self.current_bowler_index].current_frame + 1}")
	'''
	def process_ball(self, result: List[int]):
		""" Canadian 5-pin bowling process_ball with proper 10th frame logic"""
		process_start_time = time.time()
		logger.info(f"SCORING_START: Processing ball result: {result}")
		
		if not self.game_started or self.hold_active:
			logger.info("Game not active or on hold")
			return
	
		bowler = self.bowlers[self.current_bowler_index]
		frame = bowler.frames[bowler.current_frame]
		
		# CRITICAL: Pass game context to machine for last ball detection
		if hasattr(self.parent, 'machine'):
			self.parent.machine.game_context = self
		
		# Check for correction flags that need handling
		if hasattr(bowler, 'correction_flags'):
			current_frame_idx = bowler.current_frame
			if current_frame_idx in bowler.correction_flags:
				flag_info = bowler.correction_flags[current_frame_idx]
				if flag_info.get('needs_continuation', False):
					logger.info(f"CORRECTION_CONTINUATION: Frame {current_frame_idx+1} continuing after correction")
					# Clear the flag since we're handling it
					del bowler.correction_flags[current_frame_idx]
					# Continue with normal ball processing - don't skip
	
		# Pass game context to machine for ball detection
		if hasattr(self.parent, 'machine'):
			self.parent.machine.game_context = self
	
		# Safety check - don't process if frame is already complete
		if bowler.current_frame < 9 and len(frame.balls) >= 3:
			logger.warning(f"Frame {bowler.current_frame+1} already has {len(frame.balls)} balls - ignoring input")
			return
		elif bowler.current_frame == 9 and len(frame.balls) >= 3:
			logger.warning("10th frame already has 3 balls - ignoring input")
			return
	
		# CANADIAN 5-PIN: Determine ball processing method
		is_10th_frame = (bowler.current_frame == 9)
		pins_were_reset = False
		
		if is_10th_frame and len(frame.balls) >= 1:
			# In 10th frame, pins reset after strikes and spares
			if len(frame.balls) == 1 and frame.balls[0].value == 15:
				# Previous ball was a strike - pins were reset
				pins_were_reset = True
				logger.info("CANADIAN_5PIN: Pins reset after 10th frame strike")
			elif len(frame.balls) == 2:
				first_ball = frame.balls[0].value
				second_ball = frame.balls[1].value
				if first_ball + second_ball == 15:
					# Previous two balls made a spare - pins were reset
					pins_were_reset = True
					logger.info("CANADIAN_5PIN: Pins reset after 10th frame spare")
				elif first_ball == 15:
					# First ball was strike, so pins were reset for second ball
					pins_were_reset = True
					logger.info("CANADIAN_5PIN: Pins reset after strike (third ball)")
	
		# Determine ball result processing
		actual_ball_result = result.copy()
		logger.info(f"Results from Machine: {actual_ball_result}")
		
		if len(frame.balls) == 0:
			# First ball - always use machine reading directly
			actual_ball_result = result.copy()
			logger.info("SCORING_FIRST_BALL: Using machine reading directly")
			
		elif pins_were_reset:
			# CANADIAN 5-PIN: After strike/spare in 10th frame, use machine reading directly
			actual_ball_result = result.copy()
			logger.info("10TH_FRAME_RESET: Using machine reading directly (pins were reset)")
			logger.info(f"Machine reported: {result}, Using directly after reset")
			
		else:
			# CANADIAN 5-PIN: Ball-only calculation for continuing frames
			cumulative_pins_down = [0, 0, 0, 0, 0]
			for ball in frame.balls:
				for i, pin in enumerate(ball.pin_config):
					if pin == 1:
						cumulative_pins_down[i] = 1
			
			# Calculate what THIS ball knocked down (only pins still standing)
			ball_only_result = [0, 0, 0, 0, 0]
			for i, pin in enumerate(result):
				if pin == 1 and cumulative_pins_down[i] == 0:
					ball_only_result[i] = 1
			
			actual_ball_result = ball_only_result
			logger.info("SCORING_BALL_ONLY: Standard ball-only calculation")
			logger.info(f"Machine reported: {result}, Ball-only: {ball_only_result}")
	
		# CANADIAN 5-PIN: Calculate ball value (lTwo=2, lThree=3, cFive=5, rThree=3, rTwo=2)
		ball_value = sum(a * b for a, b in zip(actual_ball_result, self.settings.pin_values))
		
		# Determine symbol using symbol manager
		ball_number = len(frame.balls)
		symbol = self.symbol_manager.determine_symbol(actual_ball_result, ball_value, frame, ball_number)
		
		logger.info(f"SCORING_SYMBOL: Determined symbol '{symbol}' (value: {ball_value})")
		
		# Show symbol popup if appropriate
		if self.symbol_manager.should_show_popup(symbol, len(frame.balls), frame):
			parent_window = self.parent if hasattr(self, 'parent') else self.frame
			self.symbol_manager.show_symbol_popup(symbol, parent_window)
		
		# Create ball result
		ball_result = BallResult(pin_config=result, symbol=symbol, value=ball_value)
		frame.balls.append(ball_result)
		
		# Canadian 5-Pin frame completion logic with proper 10th frame handling
		frame_complete = False
		needs_frame_advance = False
		needs_pin_reset = False
		
		# Check for strike (all 5 pins = 15 points)
		if ball_result.value == 15:
			frame.is_strike = True
			logger.info("SCORING_STRIKE: Strike detected (15 points)")
			
			if bowler.current_frame < 9:
				# Regular frame: strike ends the frame
				needs_frame_advance = True
				frame_complete = True
				needs_pin_reset = True
			elif is_10th_frame:
				# 10th frame: strike requires pin reset but frame continues
				needs_pin_reset = True
				logger.info("10TH_FRAME_STRIKE: Strike in 10th frame, resetting pins")
				# CRITICAL: 10th frame NEVER completes after just one strike
				
		elif len(frame.balls) == 2:
			# Check for spare after second ball
			total_value = sum(ball.value for ball in frame.balls)
			if total_value == 15:
				frame.is_spare = True
				logger.info("SCORING_SPARE: Spare detected (15 points total)")
				
				if bowler.current_frame < 9:
					# Regular frame: spare ends the frame
					needs_frame_advance = True
					frame_complete = True
					needs_pin_reset = True
				elif is_10th_frame:
					# 10th frame: spare requires pin reset but frame continues for 3rd ball
					needs_pin_reset = True
					logger.info("10TH_FRAME_SPARE: Spare in 10th frame, resetting pins for 3rd ball")
					# CRITICAL: 10th frame NEVER completes after just a spare
			else:
				# Canadian 5-Pin completion logic
				if bowler.current_frame < 9:
					# Regular frame: continue to third ball (no frame advance yet)
					logger.info("CANADIAN_5PIN: Regular frame continues to third ball")
					# No frame advance, no reset - continue playing
				else:
					# CRITICAL FIX: Canadian 5-Pin 10th frame ALWAYS requires 3 balls
					# Even if no strike/spare after 2 balls, must continue to 3rd ball
					logger.info("CANADIAN_5PIN: 10th frame continues to mandatory 3rd ball")
					# NO frame completion yet - must wait for 3rd ball
		
		elif len(frame.balls) == 3:
			# Third ball - ALWAYS completes frame in Canadian 5-pin
			if bowler.current_frame < 9:
				# Regular frame: always complete after 3 balls
				needs_frame_advance = True
				frame_complete = True
				needs_pin_reset = True
				logger.info("CANADIAN_5PIN: Regular frame complete after 3 balls")
			else:
				# 10th frame ALWAYS completes after 3rd ball
				logger.info("SCORING_10TH_3BALLS_COMPLETE: 10th frame complete with mandatory 3 balls")
				frame_complete = True
	
		# Calculate scores for all frames
		self._calculate_all_scores(bowler)
		
		# Handle frame advancement and pin resets
		if needs_frame_advance:
			logger.info("SCORING_ADVANCE: Advancing frame")
			self._advance_frame(bowler)
			
			if needs_pin_reset:
				logger.info("FRAME_ADVANCE_RESET: Scheduling pin reset for new frame")
				self._schedule_immediate_full_reset('frame_advance')
		
		elif needs_pin_reset and is_10th_frame:
			# 10th frame strike/spare: reset pins but don't advance frame
			logger.info("10TH_FRAME_PIN_RESET: Resetting pins after strike/spare in 10th frame")
			self._schedule_immediate_full_reset('10th_frame_reset')
		
		elif frame_complete and bowler.current_frame == 9:
			# 10th frame complete only after 3rd ball
			logger.info("SCORING_10TH_COMPLETE: 10th frame complete after mandatory 3 balls")
			self._end_bowler_game(bowler)
			
			# Reset pins for next bowler if any remain
			if any(b.current_frame < 10 and not getattr(b, 'game_completed', False) for b in self.bowlers):
				self._schedule_immediate_full_reset('bowler_complete')
		
		# Update UI
		self.update_ui()
		
		logger.info(f"SCORING_COMPLETE: Processed in {time.time() - process_start_time:.3f}s")
	'''
		
	def _move_to_next_bowler(self):
		"""Move to next bowler and set full reset flag"""
		logger.info("_move_to_next_bowler called")
		
		if not self.game_started:
			logger.warning("Game not started, cannot move to next bowler")
			return
		
		# Store original bowler info
		original_index = self.current_bowler_index
		original_bowler = self.bowlers[original_index]
		
		# Find next active bowler who hasn't completed all frames
		next_bowler_found = False
		attempts = 0
		
		while attempts < len(self.bowlers):
			# Move to next bowler in sequence
			self.current_bowler_index = (self.current_bowler_index + 1) % len(self.bowlers)
			next_bowler = self.bowlers[self.current_bowler_index]
			
			# Check if this bowler can still play (hasn't completed all 10 frames)
			if next_bowler.current_frame < 10:
				next_bowler_found = True
				break
				
			attempts += 1
		
		# If no active bowler found, check if game should end
		if not next_bowler_found:
			logger.info("No active bowlers remaining, ending game")
			self._end_game()
			return
		
		# Log the bowler change
		logger.info(f"Moving from bowler {original_bowler.name} to {self.bowlers[self.current_bowler_index].name}")
		
		# Set full reset flag for new bowler
		logger.info("BOWLER_CHANGE: Setting full reset flag for new bowler")
		if hasattr(self.parent, 'machine'):
			self.parent.machine._force_full_reset = True
	
		# Update UI and displays
		self.update_ui()
		
		current_bowler = self.bowlers[self.current_bowler_index]
		if hasattr(self, 'parent') and hasattr(self.parent, 'set_game_display'):
			self.parent.set_game_display(f"Current Bowler: {current_bowler.name}")

	def reset_pins(self):
		"""Manual reset via button - do immediate reset"""
		if not self.game_started:
			logger.info("Cannot reset pins: Game has not started.")
			return

		logger.info("Manual reset_pins requested - executing immediately")
		
		# Enhanced debugging for reset button
		logger.info(f"RESET_DEBUG: Game started: {self.game_started}")
		logger.info(f"RESET_DEBUG: Hold active: {getattr(self, 'hold_active', 'Not set')}")
		logger.info(f"RESET_DEBUG: Parent exists: {hasattr(self, 'parent')}")
		logger.info(f"RESET_DEBUG: Parent machine exists: {hasattr(self.parent, 'machine') if hasattr(self, 'parent') else 'No parent'}")
		
		# For manual reset button, do immediate reset via machine
		if hasattr(self.parent, 'machine'):
			logger.info("MANUAL_RESET: Calling machine reset_pins directly")
			self.parent.machine.reset_pins()
		else:
			logger.error("No machine available for manual reset")
	
	def _show_symbol_popup(self, symbol: str, machine_instance=None):
		"""Show a symbol popup during machine operations."""
		if not hasattr(self, 'symbol_popup'):
			# Create symbol popup instance
			popup_parent = self.parent if hasattr(self, 'parent') else self.frame
			popup_settings = {
				'background_color': self.settings.background_color,
				'foreground_color': self.settings.foreground_color,
				'symbol_color': 'yellow'
			}
			self.symbol_popup = SymbolPopup(
				parent_window=popup_parent,
				settings=popup_settings
			)
		
		# Show the popup
		self.symbol_popup.show_symbol(symbol, machine_instance)

		
	def _check_if_next_bowler_needs_reset(self):
		"""Check if the next bowler will need reset pins"""
		# Find next active bowler
		next_idx = (self.current_bowler_index + 1) % len(self.bowlers)
		next_bowler = self.bowlers[next_idx]
		
		# If next bowler is starting a new frame, they need reset
		return next_bowler.current_frame == 0 or (
			next_bowler.current_frame < 10 and 
			len(next_bowler.frames[next_bowler.current_frame].balls) == 0
		)
		
	def _calculate_all_scores(self, bowler: Bowler):
		"""FIXED: Calculate all frame scores with proper strike/spare detection."""
		running_total = 0
		
		for i, frame in enumerate(bowler.frames):
			if not frame.balls:
				continue
			
			# Calculate frame value with bonus
			base_value = sum(b.value for b in frame.balls)
			bonus = 0
			
			# FIXED: Reset frame status before recalculation
			frame.is_strike = False
			frame.is_spare = False
			
			# Check for strike (ONLY first ball = 15)
			if len(frame.balls) >= 1 and frame.balls[0].value == 15:
				frame.is_strike = True
				logger.info(f"Frame {i+1} detected as STRIKE (first ball = 15)")
			
			# Check for spare (first two balls = 15, NOT a strike)
			elif len(frame.balls) >= 2:
				first_ball_value = frame.balls[0].value
				second_ball_value = frame.balls[1].value
				first_two_value = first_ball_value + second_ball_value
				
				if first_two_value == 15 and first_ball_value < 15:
					frame.is_spare = True
					logger.info(f"Frame {i+1} detected as SPARE ({first_ball_value} + {second_ball_value} = 15)")
			
			# FIXED: 10th frame has NO bonus calculations - just sum the balls
			if i == 9:  # 10th frame (index 9)
				frame_score = base_value
				logger.info(f"Frame 10: base={base_value}, NO BONUS, frame_score={frame_score}")
			else:
				# Frames 1-9: calculate bonuses based on CORRECTED status
				if frame.is_strike:
					bonus = self._calculate_strike_bonus(bowler, i)
					frame.bonus_balls = self._get_bonus_balls_for_db(bowler, i, 'strike')
					logger.info(f"Frame {i+1}: STRIKE bonus calculation, bonus={bonus}")
				elif frame.is_spare:
					bonus = self._calculate_spare_bonus(bowler, i)
					frame.bonus_balls = self._get_bonus_balls_for_db(bowler, i, 'spare')
					logger.info(f"Frame {i+1}: SPARE bonus calculation, bonus={bonus}")
				else:
					# No bonus for open frames
					frame.bonus_balls = []
					logger.info(f"Frame {i+1}: OPEN frame, no bonus")
					
				frame_score = base_value + bonus
			
			# Add frame score to running total
			running_total += frame_score
			frame.total = running_total
			
			# Store breakdown for display
			frame.base_score = base_value
			frame.bonus_score = bonus
			
			logger.info(f"Frame {i+1}: base={base_value}, bonus={bonus}, frame_score={frame_score}, cumulative={running_total}")
		
		bowler.total_score = running_total
		logger.info(f"Bowler {bowler.name} total score: {running_total}")

	def _calculate_spare_bonus_across_bowlers(self, bowler: Bowler, frame_idx: int) -> int:
		"""Calculate bonus points for a spare, looking across all bowlers if needed."""
		# First try to find bonus in this bowler's subsequent frames
		for j in range(frame_idx + 1, len(bowler.frames)):
			if bowler.frames[j].balls:
				return bowler.frames[j].balls[0].value
		
		# If no subsequent frames, look at the next bowler's frames
		bowler_index = self.bowlers.index(bowler)
		
		# Check if we need to look at other bowlers for bonus
		if bowler.current_frame <= frame_idx:  # This bowler hasn't completed enough frames
			# Look at next bowler
			next_bowler_index = (bowler_index + 1) % len(self.bowlers)
			next_bowler = self.bowlers[next_bowler_index]
			
			# Get the next ball from next bowler's frames
			for frame in next_bowler.frames:
				if frame.balls:
					return frame.balls[0].value
		
		return 0
	
	def _calculate_strike_bonus_across_bowlers(self, bowler: Bowler, frame_idx: int) -> int:
		"""Calculate bonus points for a strike, looking across all bowlers if needed."""
		next_balls = []
		
		# First try current bowler
		for j in range(frame_idx + 1, len(bowler.frames)):
			if bowler.frames[j].balls:
				next_balls.extend(bowler.frames[j].balls)
				if len(next_balls) >= 2:
					break
		
		# If still need more balls, look at other bowlers
		if len(next_balls) < 2:
			bowler_index = self.bowlers.index(bowler)
			next_bowler_index = (bowler_index + 1) % len(self.bowlers)
			next_bowler = self.bowlers[next_bowler_index]
			
			for frame in next_bowler.frames:
				if frame.balls:
					next_balls.extend(frame.balls)
					if len(next_balls) >= 2:
						break
		
		return sum(b.value for b in next_balls[:2])

	def _calculate_strike_bonus(self, bowler: Bowler, frame_idx: int) -> int:
		"""Fixed strike bonus calculation - next 2 balls only, excludes 10th frame."""
		if frame_idx >= 9:  # 10th frame strikes don't get bonus
			return 0
			
		next_balls = []
		balls_found = 0
		
		# Look for next 2 balls in subsequent frames
		for j in range(frame_idx + 1, len(bowler.frames)):
			if bowler.frames[j].balls and balls_found < 2:
				for ball in bowler.frames[j].balls:
					if balls_found < 2:
						next_balls.append(ball)
						balls_found += 1
					if balls_found >= 2:
						break
			if balls_found >= 2:
				break
		
		bonus = sum(b.value for b in next_balls[:2])
		logger.info(f"Strike bonus for frame {frame_idx+1}: next 2 balls = {[b.value for b in next_balls[:2]]}, bonus = {bonus}")
		return bonus

	def _calculate_spare_bonus(self, bowler: Bowler, frame_idx: int) -> int:
		"""Fixed spare bonus calculation - next 1 ball only, excludes 10th frame."""
		if frame_idx >= 9:  # 10th frame spares don't get bonus
			return 0
			
		# Look for next 1 ball in subsequent frames
		for j in range(frame_idx + 1, len(bowler.frames)):
			if bowler.frames[j].balls:
				bonus = bowler.frames[j].balls[0].value
				logger.info(f"Spare bonus for frame {frame_idx+1}: next ball = {bonus}")
				return bonus
		
		logger.info(f"Spare bonus for frame {frame_idx+1}: no next ball found, bonus = 0")
		return 0
	
	def _get_bonus_balls_for_db(self, bowler: Bowler, frame_idx: int, bonus_type: str) -> List[Dict]:
		"""Get bonus balls used for a strike or spare frame for database storage."""
		bonus_balls = []
		
		if bonus_type == 'strike':
			# Strike uses next 2 balls
			balls_found = 0
			for j in range(frame_idx + 1, len(bowler.frames)):
				if bowler.frames[j].balls:
					for ball in bowler.frames[j].balls:
						if balls_found < 2:
							bonus_balls.append({
								"frame": j + 1,
								"ball": balls_found + 1,
								"pin_config": ball.pin_config,
								"symbol": ball.symbol,
								"value": ball.value
							})
							balls_found += 1
						if balls_found >= 2:
							break
				if balls_found >= 2:
					break
					
		elif bonus_type == 'spare':
			# Spare uses next 1 ball
			for j in range(frame_idx + 1, len(bowler.frames)):
				if bowler.frames[j].balls:
					ball = bowler.frames[j].balls[0]
					bonus_balls.append({
						"frame": j + 1,
						"ball": 1,
						"pin_config": ball.pin_config,
						"symbol": ball.symbol,
						"value": ball.value
					})
					break
		
		return bonus_balls
	
	def _get_strike_bonus_balls_for_display(self, bowler: Bowler, frame_idx: int) -> List[BallResult]:
		"""Get the next 2 balls used as bonus for a strike frame for display purposes."""
		bonus_balls = []
		balls_found = 0
		
		for j in range(frame_idx + 1, len(bowler.frames)):
			if bowler.frames[j].balls and balls_found < 2:
				for ball in bowler.frames[j].balls:
					if balls_found < 2:
						bonus_balls.append(ball)
						balls_found += 1
					if balls_found >= 2:
						break
			if balls_found >= 2:
				break
		
		return bonus_balls
	
	def _get_spare_bonus_ball_for_display(self, bowler: Bowler, frame_idx: int) -> Optional[BallResult]:
		"""Get the next 1 ball used as bonus for a spare frame for display purposes."""
		for j in range(frame_idx + 1, len(bowler.frames)):
			if bowler.frames[j].balls:
				return bowler.frames[j].balls[0]
		return None
	
	def _is_strike_in_active_streak(self, bowler: Bowler, frame_idx: int) -> bool:
		"""Check if a strike is part of an active streak."""
		if frame_idx >= 9:  # 10th frame - always show total
			return False
		
		next_frame = bowler.frames[frame_idx + 1]
		
		# If next frame has no balls yet, this strike is in an active streak
		if not next_frame.balls:
			return True
		
		# If next frame is also a strike, this strike is in an active streak
		if next_frame.is_strike:
			return True
		
		return False
	
	def _validate_perfect_game_score(self, bowler: Bowler):
		"""Validate that a perfect game scores exactly 450."""
		# Check if all frames are strikes
		all_strikes = True
		for i, frame in enumerate(bowler.frames):
			if i < 9:  # Frames 1-9
				if not (frame.balls and frame.balls[0].value == 15):
					all_strikes = False
					break
			else:  # 10th frame
				if not (len(frame.balls) == 3 and 
					   all(ball.value == 15 for ball in frame.balls)):
					all_strikes = False
					break
		
		if all_strikes:
			expected_score = 450  # Perfect game in Canadian 5-pin
			if bowler.total_score != expected_score:
				logger.error(f"PERFECT GAME ERROR: Expected {expected_score}, got {bowler.total_score}")
				# Fix the score
				bowler.total_score = expected_score
				bowler.frames[9].total = expected_score
			else:
				logger.info(f"PERFECT GAME: Correctly scored {expected_score}")
	
	def _print_frame_status(self, bowler: Bowler):
		"""Print debugging information about all frames."""
		logger.info("\n--- Bowler Frames State ---")
		for idx, frame in enumerate(bowler.frames):
			# Format balls with appropriate display
			balls_str = ", ".join([f"Ball {i+1}: {ball.value} ({ball.symbol})" 
								 for i, ball in enumerate(frame.balls)])
			logger.info(f"Frame {idx + 1}: {balls_str}, Total={frame.total}, Strike={frame.is_strike}, Spare={frame.is_spare}")
		logger.info(f"Bowler Total Score: {bowler.total_score}")

	def _advance_frame(self, bowler: Bowler):
		""" Advance frame with correction flag cleanup."""
		if bowler.current_frame < 9:
			# Clear correction flags when frame actually completes
			current_frame_idx = bowler.current_frame
			
			# Clear correction flags for the completing frame
			if hasattr(bowler, 'correction_flags') and current_frame_idx in bowler.correction_flags:
				logger.info(f"CORRECTION_COMPLETE: Clearing correction flag for completed frame {current_frame_idx+1}")
				del bowler.correction_flags[current_frame_idx]
			
			# Clear active correction flag
			if hasattr(bowler, 'frame_correction_active') and current_frame_idx in bowler.frame_correction_active:
				logger.info(f"CORRECTION_ACTIVE_CLEAR: Clearing active correction for frame {current_frame_idx+1}")
				del bowler.frame_correction_active[current_frame_idx]
			
			bowler.current_frame += 1
			logger.info(f"Advanced {bowler.name} to frame {bowler.current_frame + 1}")
		else:
			# End of game for this bowler
			logger.info(f"Bowler {bowler.name} completed all frames")
			self._end_bowler_game(bowler)
			return
		
		# Check frames_per_turn to determine when to switch bowlers
		frames_completed_this_turn = (bowler.current_frame % self.settings.frames_per_turn) 
		
		if frames_completed_this_turn == 0:
			# Check if this is a paired lane game (league game)
			if hasattr(self, 'paired_lane') and self.paired_lane:
				logger.info(f"{bowler.name} completed {self.settings.frames_per_turn} frames, moving to paired lane {self.paired_lane}")
				self._move_bowler_to_paired_lane(bowler)
			else:
				logger.info(f"{bowler.name} completed {self.settings.frames_per_turn} frame(s), moving to next bowler")
				self._move_to_next_bowler()
		else:
			logger.info(f"{bowler.name} continues with frame {bowler.current_frame + 1}")
		
		# Reset the button label back to "RESET" when the frame ends
		if hasattr(self, 'ui_manager'):
			self.ui_manager.set_reset_button_to_normal()

	def _calculate_bonus_balls(self, bowler: Bowler, frame_idx: int) -> List[Dict]:
		"""Calculate and return bonus balls used for a strike or spare frame for statistics."""
		frame = bowler.frames[frame_idx]
		bonus_balls = []
		
		if frame.is_strike:
			next_balls = self._get_next_balls(bowler, frame_idx, 2)
			for ball in next_balls:
				bonus_balls.append({
					"pin_config": ball.pin_config,
					"symbol": ball.symbol,
					"value": ball.value
				})
		elif frame.is_spare:
			next_balls = self._get_next_balls(bowler, frame_idx, 1)
			for ball in next_balls:
				bonus_balls.append({
					"pin_config": ball.pin_config,
					"symbol": ball.symbol,
					"value": ball.value
				})
				
		return bonus_balls

	def _get_next_balls(self, bowler: Bowler, frame_idx: int, count: int) -> List[BallResult]:
		"""Get the next 'count' balls after the specified frame."""
		next_balls = []
		for j in range(frame_idx + 1, len(bowler.frames)):
			if bowler.frames[j].balls:
				next_balls.extend(bowler.frames[j].balls)
				if len(next_balls) >= count:
					break
					
		return next_balls[:count]

	def _move_bowler_to_paired_lane(self, bowler: Bowler):
		"""Move the bowler to the paired lane after completing their frames_per_turn."""
		if not self.paired_lane:
			logger.warning(f"No paired lane configured for lane {self.lane_id}")
			return
			
		logger.info(f"Moving bowler {bowler.name} to the paired lane {self.paired_lane}")
		
		# Prepare bowler data to send to paired lane
		bowler_data = {
			"name": bowler.name,
			"handicap": bowler.handicap,
			"frames": [
				{
					"balls": [
						{
							"pin_config": ball.pin_config,
							"symbol": ball.symbol,
							"value": ball.value
						} for ball in frame.balls
					],
					"total": frame.total,
					"is_strike": frame.is_strike,
					"is_spare": frame.is_spare
				} for frame in bowler.frames
			],
			"current_frame": bowler.current_frame,
			"total_score": bowler.total_score,
			"from_lane": self.lane_id,
			"to_lane": self.paired_lane,
			"absent": getattr(bowler, "absent", False),
			"default_score": getattr(bowler, "default_score", None)
		}
		
		# Create and send asynchronous task to send bowler data
		self._send_bowler_data_async(bowler_data)
		
		# Remove bowler from this lane
		# Remove bowler from this lane but preserve UI state
		# Store UI state before removing bowler
		ui_was_initialized = getattr(self.ui_manager, 'ui_initialized', False)
		
		# Remove bowler from list but don't trigger full UI rebuild
		if bowler in self.bowlers:
			bowler_index = self.bowlers.index(bowler)
			self.bowlers.remove(bowler)
			
			# Adjust current_bowler_index if needed
			if self.current_bowler_index >= len(self.bowlers) and len(self.bowlers) > 0:
				self.current_bowler_index = 0
			elif self.current_bowler_index > bowler_index:
				self.current_bowler_index -= 1
			
			# Preserve UI initialization state
			if ui_was_initialized:
				self.ui_manager.ui_initialized = True
		
		# NEW: Check if any active bowlers remain
		if not self._check_for_active_bowlers():
			self._show_no_active_bowlers_ui()
		else:
			# Move to next available bowler
			self._move_to_next_bowler()
	def _end_game(self):
		"""End the game for all bowlers."""
		logger.info("Game Over")
		
		# Reset pins
		if 'reset_pins' in dispatcher.listeners and dispatcher.listeners['reset_pins']:
			self.reset_pins()
			
		# Update display
		if hasattr(self.parent, 'set_game_display'):
			self.parent.set_game_display("GAME OVER")
		
		# Save the current game data
		self._save_current_game_data()
		
		# Update the UI to show "GAME OVER"
		self.update_ui()
	
		self.game_started = False  # Reset game state
		
		# Disable buttons
		self.ui_manager.enable_buttons(False)
	
		# Check if more games are scheduled (game count based)
		if self.settings.total_games is not None:
			if self.current_game_number < self.settings.total_games:
				# Show Next Game button
				self._show_next_game_button()
			else:
				# Start the end timer
				self._start_end_timer()
		
		# Check if more games allowed (time based)
		elif self.settings.total_time is not None:
			# Calculate remaining time
			if self.game_start_time is not None and self.total_game_time_minutes is not None:
				elapsed_seconds = time.time() - self.game_start_time
				elapsed_minutes = elapsed_seconds / 60
				remaining_minutes = self.total_game_time_minutes - elapsed_minutes
				
				if remaining_minutes > 5:  # Need at least 5 minutes for another game
					logger.info(f"Time remaining: {remaining_minutes:.1f} minutes - allowing new game")
					# Show Next Game button for time-based games
					self._show_next_game_button()
				else:
					logger.info(f"Insufficient time remaining: {remaining_minutes:.1f} minutes")
					# Start the end timer
					self._start_end_timer()
			else:
				# Fallback: start end timer
				self._start_end_timer()

	def _save_current_game_data(self):
		"""Save the current game data with timestamp including detailed ball information and bonuses."""
		game_record = {
			"game_number": self.current_game_number,
			"date": datetime.now().strftime("%Y-%m-%d"),
			"time": datetime.now().strftime("%H:%M:%S"),
			"bowlers": [
				{
					"name": bowler.name,
					"frames": [
						{
							"balls": [
								{
									"pin_config": ball.pin_config,
									"symbol": ball.symbol,
									"value": ball.value
								} for ball in frame.balls
							],
							"bonus_balls": getattr(frame, 'bonus_balls', []),  # Include bonus ball details
							"base_score": getattr(frame, 'base_score', sum(ball.value for ball in frame.balls) if frame.balls else 0),
							"bonus_score": getattr(frame, 'bonus_score', 0),
							"total": frame.total,
							"is_strike": frame.is_strike,
							"is_spare": frame.is_spare
						} for i, frame in enumerate(bowler.frames)
					],
					"total_score": bowler.total_score,
					"fouls": bowler.fouls,
					"prize": bowler.prize
				} for bowler in self.bowlers
			]
		}
		self.game_data.append(game_record)
		
		# Save to database
		self._save_to_database(game_record)


	def _save_to_database(self, game_record):
		"""Save game data to the bowling database file."""
		try:
			# Create the database directory if it doesn't exist
			os.makedirs('database', exist_ok=True)
			
			db_file = 'database/bowling.db'
			
			# Load existing data if file exists
			existing_data = []
			if os.path.exists(db_file):
				with open(db_file, 'r') as f:
					existing_data = json.load(f)
			
			# Append new game record
			existing_data.append(game_record)
			
			# Save back to file
			with open(db_file, 'w') as f:
				json.dump(existing_data, f, indent=2)
				
			logger.info(f"Game {self.current_game_number} data saved to database")
		except Exception as e:
			logger.error(f"Error saving game data: {str(e)}")

	def _update_next_game_countdown(self):
		"""Update the next game countdown and auto-start if reaches 0."""
		if not hasattr(self, 'next_game_countdown') or not self.next_game_countdown:
			return
			
		self.next_game_countdown_seconds -= 1
		
		try:
			self.next_game_countdown.config(text=f"Starting in: {self.next_game_countdown_seconds}")
		except tk.TclError:
			# Widget was destroyed
			return
		
		if self.next_game_countdown_seconds <= 0:
			# Auto-start the next game
			self._start_next_game()
		else:
			# Schedule the next update in 1 second
			if hasattr(self, 'frame') and self.frame:
				self.frame.after(1000, self._update_next_game_countdown)
				
	def _start_end_timer(self):
		"""Start the 60-second timer when all games are complete."""
		logger.info("Starting End Game Timmer")
		self.timer_running = True
		self.timer_seconds = 60
		
		# Create container for timer
		timer_container = tk.Frame(self.ui_manager.button_container, bg=self.settings.background_color)
		timer_container.pack(fill=tk.X, pady=5)
		
		# Create timer label
		self.timer_label = tk.Label(
			timer_container,
			text=f"Clearing in: {self.timer_seconds}s",
			bg=self.settings.background_color,
			fg="red",
			font=("Arial", 16)
		)
		self.timer_label.pack()
			
		# Start timer countdown
		self._update_timer()

	def _update_timer(self):
		"""Update the timer display and handle expiration."""
		logger.info("Starting Update Timmer")
		if not self.timer_running:
			return
			
		self.timer_seconds -= 1
		
		if self.timer_label:
			self.timer_label.config(text=f"Clearing in: {self.timer_seconds}s")
			
		if self.timer_seconds <= 0:
			self._clear_game_completely()
		else:
			# Schedule next update in 1 second
			self.frame.after(1000, self._update_timer)

	def _clear_game_completely(self):
		"""Clear all game data and reset the screen completely for next game."""
		logger.info("Clearing game completely and resetting for next game")
		self.timer_running = False
		
		# Save all game data one final time
		# TODO: Restore this in network
		#self.send_game_data_to_server()
		
		# Clear all game data
		self.clear_game_data()
		
		# CRITICAL: Stop all timers and background processes
		if hasattr(self, 'practice_timer_label') and self.practice_timer_label:
			self.practice_timer_label = None
		if hasattr(self, 'timer_label') and self.timer_label:
			self.timer_label = None
		
		# Clear the frame completely and safely
		self._safe_clear_all_widgets()
		
		# Completely reset UI manager state
		if hasattr(self, 'ui_manager'):
			# Clear all cached data
			self.ui_manager._widget_cache = {}
			self.ui_manager.ui_initialized = False
			
			# Clear all widget references
			self.ui_manager.header_labels = []
			self.ui_manager.bowler_name_labels = []
			self.ui_manager.frame_subframes = []
			self.ui_manager.ball_labels = []
			self.ui_manager.total_labels = []
			self.ui_manager.bowler_total_labels = []
			self.ui_manager.button_container = None
			self.ui_manager.button_frame = None
			
			# Clear button references
			self.ui_manager.hold_button = None
			self.ui_manager.skip_button = None
			self.ui_manager.reset_button = None
			self.ui_manager.settings_button = None
		
		# Reset all game state completely
		self.game_started = False
		self.hold_active = False
		self.current_bowler_index = 0
		self.current_game_number = 1
		self.game_data = []
		
		# Clear bowlers data
		self.bowlers = []
		
		# Reset time-related variables
		self.game_start_time = None
		self.time_warning_shown = False
		if hasattr(self, 'total_game_time_minutes'):
			self.total_game_time_minutes = None
		
		# Clear any remaining popup windows
		self._close_all_popup_windows()
		
		# Reset parent display states
		if hasattr(self.parent, 'set_game_display'):
			self.parent.set_game_display("No Game Active")
		if hasattr(self.parent, 'set_info_label'):
			self.parent.set_info_label("Games Remaining: 0")
		if hasattr(self.parent, 'set_scroll_message'):
			from event_dispatcher import dispatcher
			if 'scroll_message' in dispatcher.listeners:
				dispatcher.listeners['scroll_message'][0]("Game cleared. Ready for new game registration.")
		
		# Update lane status
		if hasattr(self.parent, 'update_lane_status'):
			self.parent.update_lane_status("idle")
		
		# Create a clean welcome screen
		self._create_welcome_screen()
		
		logger.info("Game completely cleared and reset - ready for new game")
	
	def _safe_clear_all_widgets(self):
		"""Safely clear all widgets without Tkinter errors"""
		try:
			if not hasattr(self, 'frame') or not self.frame:
				logger.warning("No frame to clear")
				return
			
			# Get list of all children first
			children = list(self.frame.winfo_children())
			logger.info(f"Clearing {len(children)} widgets from frame")
			
			# Destroy each widget safely
			for widget in children:
				try:
					if widget.winfo_exists():
						widget.destroy()
				except tk.TclError as e:
					logger.warning(f"Error destroying widget: {e}")
					continue
				except Exception as e:
					logger.warning(f"Unexpected error destroying widget: {e}")
					continue
			
			# Force update to ensure destruction is complete
			self.frame.update_idletasks()
			
			# Verify all widgets are cleared
			remaining = len(self.frame.winfo_children())
			if remaining > 0:
				logger.warning(f"{remaining} widgets remain after clearing")
			else:
				logger.info("All widgets successfully cleared")
			
		except Exception as e:
			logger.error(f"Error in safe widget clearing: {e}")
	
	def _close_all_popup_windows(self):
		"""Close any remaining popup windows"""
		popup_attrs = [
			'settings_window',
			'score_correction_window', 
			'pin_set_window',
			'display_settings_window'
		]
		
		for attr in popup_attrs:
			if hasattr(self, attr):
				try:
					window = getattr(self, attr)
					if window and window.winfo_exists():
						window.grab_release()
						window.destroy()
					delattr(self, attr)
				except Exception as e:
					logger.warning(f"Error closing {attr}: {e}")
	
	def _create_welcome_screen(self):
		"""Create a clean welcome screen for new game registration"""
		try:
			# Create main welcome container
			welcome_container = tk.Frame(self.frame, bg=self.settings.background_color)
			welcome_container.pack(fill=tk.BOTH, expand=True, padx=50, pady=50)
			
			# Welcome title
			welcome_title = tk.Label(
				welcome_container,
				text=f"LANE {getattr(self.parent, 'lane_id', 'X')}",
				bg=self.settings.background_color,
				fg=self.settings.foreground_color,
				font=("Arial", 48, "bold")
			)
			welcome_title.pack(pady=(50, 30))
			
			# Status message
			status_label = tk.Label(
				welcome_container,
				text="Ready for New Game",
				bg=self.settings.background_color,
				fg="green",
				font=("Arial", 32, "bold")
			)
			status_label.pack(pady=20)
			
			# Instructions
			instructions = tk.Label(
				welcome_container,
				text="See front desk to register a new game",
				bg=self.settings.background_color,
				fg=self.settings.foreground_color,
				font=("Arial", 20)
			)
			instructions.pack(pady=20)
			
			# Emergency reset button (optional)
			emergency_frame = tk.Frame(welcome_container, bg=self.settings.background_color)
			emergency_frame.pack(side=tk.BOTTOM, pady=30)
			
			emergency_button = tk.Button(
				emergency_frame,
				text="EMERGENCY RESET",
				bg="red",
				fg="white",
				command=self._emergency_reset,
				font=("Arial", 16),
				width=20
			)
			emergency_button.pack()
			
			logger.info("Welcome screen created successfully")
			
		except Exception as e:
			logger.error(f"Error creating welcome screen: {e}")
	
	def _emergency_reset(self):
		"""Emergency reset function for troubleshooting"""
		logger.info("Emergency reset requested")
		
		try:
			# Force reset pins if machine available
			if hasattr(self.parent, 'machine'):
				self.parent.machine.reset_pins()
				logger.info("Emergency pin reset completed")
			
			# Show confirmation
			if hasattr(self.parent, 'set_scroll_message'):
				from event_dispatcher import dispatcher
				if 'scroll_message' in dispatcher.listeners:
					dispatcher.listeners['scroll_message'][0]("Emergency reset completed")
			
		except Exception as e:
			logger.error(f"Emergency reset failed: {e}")
	
	def clear_game_data(self):
		"""Clear all game-specific data structures"""
		try:
			# Clear game data list
			self.game_data = []
			
			# Reset bowler data
			for bowler in self.bowlers:
				bowler.frames = [Frame(balls=[], total=0) for _ in range(10)]
				bowler.current_frame = 0
				bowler.total_score = 0
				bowler.game_completed = False
			
			# Clear any cached data
			if hasattr(self, '_widget_cache'):
				self._widget_cache = {}
			
			# Clear symbol manager if exists
			if hasattr(self, 'symbol_manager'):
				if hasattr(self.symbol_manager, 'cleanup'):
					self.symbol_manager.cleanup()
			
			logger.info("Game data cleared successfully")
			
		except Exception as e:
			logger.error(f"Error clearing game data: {e}")
	
	def _set_display_mode_and_close(self, mode):
		"""Set display mode and close settings window."""
		self.set_display_mode(mode)
		self._close_display_settings()
			
	def _open_display_mode_settings(self):
		"""Open display mode selection."""
		mode_window = tk.Toplevel(self.settings_window)
		mode_window.title("Display Mode")
		mode_window.geometry("400x200")
		mode_window.grab_set()
		
		tk.Label(
			mode_window,
			text="Choose Display Mode:",
			font=("Arial", 14, "bold")
		).pack(pady=10)
		
		current_mode = self.settings.display_mode
		tk.Label(
			mode_window,
			text=f"Current: {current_mode.title()}",
			font=("Arial", 12)
		).pack(pady=5)
		
		# Mode buttons
		modes = [
			("Standard", "standard", "* bonus indicators, no breakdowns"),
			("Detailed", "detailed", "* indicators AND (15+8) breakdowns"), 
			("Clean", "clean", "No bonus indicators or breakdowns")
		]
		
		for name, mode_key, desc in modes:
			btn_frame = tk.Frame(mode_window)
			btn_frame.pack(fill=tk.X, padx=20, pady=5)
			
			tk.Button(
				btn_frame,
				text=name,
				command=lambda m=mode_key: self._apply_mode_and_close(m, mode_window),
				width=12
			).pack(side=tk.LEFT)
			
			tk.Label(btn_frame, text=desc, font=("Arial", 10)).pack(side=tk.LEFT, padx=10)
	
	def _apply_mode_and_close(self, mode, window):
		"""Apply display mode and close window."""
		self.set_display_mode(mode)
		window.destroy()
			
	def open_settings(self):
		"""Open the settings window with proper modal behavior."""
		if hasattr(self, 'settings_window') and self.settings_window.winfo_exists():
			self.settings_window.lift()
			return
	
		self.settings_window = tk.Toplevel(self.frame)
		self.settings_window.title("Settings")
		self.settings_window.geometry("1500x900")
		self.settings_window.protocol("WM_DELETE_WINDOW", self._close_settings)
		
		# Make it modal
		self.settings_window.grab_set()
		self.settings_window.focus_set()
		
		# Disable game input while settings are open
		self.hold_active = True
		
		# Add buttons with better error handling
		try:
			tk.Button(
				self.settings_window,
				text="Score Correction",
				command=self._safe_open_score_correction,
				font=("Arial", 16)
			).pack(pady=10, fill=tk.X, padx=20)
			
			tk.Button(
				self.settings_window,
				text="Revert Last Ball",
				command=self._safe_revert_last_ball,
				font=("Arial", 16)
			).pack(pady=10, fill=tk.X, padx=20)
			
			tk.Button(
				self.settings_window,
				text="Bowler Status",
				command=self._safe_open_bowler_status,
				font=("Arial", 16)
			).pack(pady=10, fill=tk.X, padx=20)
			
			# Add Pin Set button
			tk.Button(
				self.settings_window,
				text="Pin Set",
				command=self._safe_open_pin_set,
				font=("Arial", 16)
			).pack(pady=10, fill=tk.X, padx=20)
			
			# Combined Display Settings (removed separate Display Mode button)
			tk.Button(
				self.settings_window,
				text="Display Settings",
				command=self._safe_open_display_settings,
				font=("Arial", 16)
			).pack(pady=10, fill=tk.X, padx=20)
			
			# Close button
			tk.Button(
				self.settings_window,
				text="CLOSE",
				command=self._close_settings,
				font=("Arial", 16),
				bg="red",
				fg="white"
			).pack(side=tk.BOTTOM, pady=10, fill=tk.X, padx=20)
			
		except Exception as e:
			logger.error(f"Error creating settings buttons: {str(e)}")
			self._close_settings()
	def _close_settings(self):
		"""Properly close the settings window."""
		if hasattr(self, 'settings_window'):
			try:
				self.settings_window.grab_release()
				self.settings_window.destroy()
			except:
				pass
			del self.settings_window
		self.hold_active = False

	def show_confirmation_dialog(self, title, message, ok_command):
		# TODO: Put back later
		ok_command()
		'''
		confirm_window = tk.Toplevel(self.frame)
		confirm_window.title(title)
		confirm_window.configure(bg='black')
		confirm_window.geometry("400x200")
		
		# Make window modal
		confirm_window.transient(self.frame)
		confirm_window.grab_set()
		
		# Main frame
		main_frame = tk.Frame(confirm_window, bg='black')
		main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
		
		# Message label
		msg_label = tk.Label(
			main_frame, 
			text=message,
			bg='black',
			fg='white',
			font=("Arial", 12),
			wraplength=380,
			justify=tk.LEFT
		)
		msg_label.pack(pady=20)
		
		# Buttons frame
		buttons_frame = tk.Frame(main_frame, bg='black')
		buttons_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=10)
		
		# Cancel button
		cancel_button = tk.Button(
			buttons_frame,
			text="Cancel",
			bg="red",
			fg="white",
			command=confirm_window.destroy,
			font=("Arial", 12)
		)
		cancel_button.pack(side=tk.RIGHT, padx=10)
		
		# OK button that runs the provided command 
		def on_ok():
			confirm_window.destroy()
			ok_command()
			
		ok_button = tk.Button(
			buttons_frame,
			text="OK",
			bg="green",
			fg="white",
			command=on_ok,
			font=("Arial", 12)
		)
		ok_button.pack(side=tk.RIGHT, padx=10)
		
		# Center window on screen
		confirm_window.update_idletasks()
		width = confirm_window.winfo_width()
		height = confirm_window.winfo_height()
		x = (confirm_window.winfo_screenwidth() // 2) - (width // 2)
		y = (confirm_window.winfo_screenheight() // 2) - (height // 2)
		confirm_window.geometry(f'+{x}+{y}')
		'''
	
	def _safe_open_score_correction(self):
		"""Safely open score correction with error handling."""
		try:
			self._close_settings()  # Close settings window first
			self.open_score_correction()
		except Exception as e:
			logger.error(f"Error opening score correction: {str(e)}")
			tk.messagebox.showerror("Error", "Failed to open score correction")
	
	def _safe_revert_last_ball(self):
		"""Safely revert last ball with error handling."""
		try:
			self._close_settings()
			self.revert_last_ball()
		except Exception as e:
			logger.error(f"Error reverting last ball: {str(e)}")
			tk.messagebox.showerror("Error", "Failed to revert last ball")
	
	def _safe_open_bowler_status(self):
		"""Safely open bowler status with error handling."""
		try:
			self._close_settings()
			self.open_bowler_status()
		except Exception as e:
			logger.error(f"Error opening bowler status: {str(e)}")
			tk.messagebox.showerror("Error", "Failed to open bowler status")

	
	def open_score_correction(self):
		if hasattr(self, 'score_correction_window') and self.score_correction_window.winfo_exists():
			self.score_correction_window.lift()
			return
		
		logger.error("Started Open Score Correction")
		
		self.score_correction_window = tk.Toplevel(self.frame)
		self.score_correction_window.title("Score Correction")
		
		# Proper fullscreen setup for Raspberry Pi
		self.score_correction_window.geometry("1920x1080")
		self.score_correction_window.attributes("-fullscreen", True)
		self.score_correction_window.protocol("WM_DELETE_WINDOW", self._close_score_correction)
		
		# Make it modal
		self.score_correction_window.grab_set()
		self.score_correction_window.focus_set()
		
		# Configure for dark background
		self.score_correction_window.configure(bg='black')
		
		try:
			# Use grid layout for better control
			self.score_correction_window.grid_rowconfigure(1, weight=1)
			self.score_correction_window.grid_columnconfigure(1, weight=1)
			
			# Title bar with close button
			title_frame = tk.Frame(self.score_correction_window, bg='black', height=60)
			title_frame.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=5)
			title_frame.grid_propagate(False)
			
			tk.Label(
				title_frame,
				text="SCORE CORRECTION",
				bg='black',
				fg='white',
				font=("Arial", 24, "bold")
			).pack(side=tk.LEFT, pady=15)
			
			# Emergency close button (top right)
			tk.Button(
				title_frame,
				text="✕ CLOSE",
				bg="red",
				fg="white",
				command=self._close_score_correction,
				font=("Arial", 16, "bold"),
				width=10
			).pack(side=tk.RIGHT, pady=10)
			
			# Left panel for bowlers with fixed width
			bowlers_frame = tk.Frame(self.score_correction_window, bg='black', width=300, relief='solid', bd=2)
			bowlers_frame.grid(row=1, column=0, sticky="nsew", padx=(10, 5), pady=5)
			bowlers_frame.grid_propagate(False)  # CRITICAL: Prevent resizing
			
			# Right panel for content with proper expansion
			self.content_frame = tk.Frame(self.score_correction_window, bg='black', relief='solid', bd=2)
			self.content_frame.grid(row=1, column=1, sticky="nsew", padx=(5, 10), pady=5)
			
			# Configure grid weights for proper expansion
			self.score_correction_window.grid_columnconfigure(0, weight=0, minsize=300)  # Fixed width for bowlers
			self.score_correction_window.grid_columnconfigure(1, weight=1)  # Expandable for content
			
			# Initialize selection variables
			self.selected_bowler = None
			self.selected_frame = None
			self.selected_ball = None
			
			# Bowler selection with proper container
			bowler_title = tk.Label(
				bowlers_frame, 
				text="SELECT BOWLER", 
				bg='black', 
				fg='white', 
				font=("Arial", 16, "bold")
			)
			bowler_title.pack(pady=(10, 20))
			
			# Scrollable bowler list if many bowlers
			if len(self.bowlers) > 6:
				# Create scrollable area for many bowlers
				canvas = tk.Canvas(bowlers_frame, bg='black', highlightthickness=0)
				scrollbar = tk.Scrollbar(bowlers_frame, orient="vertical", command=canvas.yview)
				scrollable_bowlers = tk.Frame(canvas, bg='black')
				
				scrollable_bowlers.bind(
					"<Configure>",
					lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
				)
				
				canvas.create_window((0, 0), window=scrollable_bowlers, anchor="nw")
				canvas.configure(yscrollcommand=scrollbar.set)
				
				canvas.pack(side="left", fill="both", expand=True, padx=(10, 0))
				scrollbar.pack(side="right", fill="y")
				
				bowler_container = scrollable_bowlers
			else:
				# Simple container for few bowlers
				bowler_container = bowlers_frame
			
			# Create bowler buttons with better visibility and FIXED click handling
			for i, bowler in enumerate(self.bowlers):
				btn = tk.Button(
					bowler_container,
					text=f"{i+1}. {bowler.name}",
					command=lambda b=bowler: self._select_bowler_for_correction(b),
					font=("Arial", 14, "bold"),
					bg="darkblue",
					fg="white",
					width=25,
					height=2,
					wraplength=200  # Prevent text overflow
				)
				btn.pack(pady=5, padx=10, fill=tk.X)
			
			# Action buttons at bottom with proper positioning
			action_frame = tk.Frame(self.score_correction_window, bg='black', height=80)
			action_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=5)
			action_frame.grid_propagate(False)
			
			# Configure action frame grid
			action_frame.grid_columnconfigure(0, weight=1)
			action_frame.grid_columnconfigure(1, weight=1)
			action_frame.grid_columnconfigure(2, weight=1)
			
			# Clear Frame button - initially disabled
			self.clear_frame_btn = tk.Button(
				action_frame,
				text="CLEAR SELECTED FRAME",
				command=self._clear_selected_frame,
				font=("Arial", 16, "bold"),
				bg="orange",
				fg="white",
				state=tk.DISABLED,
				height=2
			)
			self.clear_frame_btn.grid(row=0, column=0, padx=5, sticky="ew")
			
			# Save button
			save_btn = tk.Button(
				action_frame,
				text="SAVE CHANGES",
				command=self._save_score_corrections,
				font=("Arial", 16, "bold"),
				bg="green",
				fg="white",
				height=2
			)
			save_btn.grid(row=0, column=1, padx=5, sticky="ew")
			
			# Cancel button
			cancel_btn = tk.Button(
				action_frame,
				text="CANCEL",
				command=self._close_score_correction,
				font=("Arial", 16, "bold"),
				bg="red",
				fg="white",
				height=2
			)
			cancel_btn.grid(row=0, column=2, padx=5, sticky="ew")
			
			# Bind Escape key to close
			self.score_correction_window.bind('<Escape>', lambda e: self._close_score_correction())
			
			# Initial content area setup
			self._show_initial_content()
			
		except Exception as e:
			logger.error(f"Error creating score correction UI: {str(e)}")
			self._close_score_correction()
			tk.messagebox.showerror("Error", "Failed to initialize score correction")
	
	def _show_initial_content(self):
		" Show initial content in the main area"""
		try:
			# Clear content frame
			for widget in self.content_frame.winfo_children():
				widget.destroy()
			
			# Welcome message
			welcome_label = tk.Label(
				self.content_frame,
				text="SELECT A BOWLER TO BEGIN",
				bg='black',
				fg='yellow',
				font=("Arial", 24, "bold")
			)
			welcome_label.pack(expand=True)
			
			# Instructions
			instructions = tk.Label(
				self.content_frame,
				text="Click on a bowler name from the left panel\nto view and edit their frames and scores",
				bg='black',
				fg='white',
				font=("Arial, 16"),
				justify=tk.CENTER
			)
			instructions.pack(expand=True)
			
		except Exception as e:
			logger.error(f"Error showing initial content: {e}")
			

	
	def _select_bowler_for_correction(self, bowler):
		""" Select a bowler for score correction with proper content area usage."""
		try:
			self.selected_bowler = bowler
			self.selected_frame = None
			self.selected_ball = None
			
			# Disable Clear Frame button until a valid frame is selected
			if hasattr(self, 'clear_frame_btn'):
				self.clear_frame_btn.config(state=tk.DISABLED)
			
			# Clear content frame safely - use the stored reference
			for widget in self.content_frame.winfo_children():
				widget.destroy()
			
			# Create content container with proper scrolling
			content_container = tk.Frame(self.content_frame, bg='black')
			content_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
			
			# Title for selected bowler
			title_label = tk.Label(
				content_container,
				text=f"FRAMES FOR {bowler.name.upper()}",
				bg='black',
				fg='yellow',
				font=("Arial", 20, "bold")
			)
			title_label.pack(pady=(0, 20))
			
			# Scrollable frame selection area
			canvas = tk.Canvas(content_container, bg='black', highlightthickness=0)
			scrollbar = tk.Scrollbar(content_container, orient="vertical", command=canvas.yview)
			scrollable_content = tk.Frame(canvas, bg='black')
			
			scrollable_content.bind(
				"<Configure>",
				lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
			)
			
			canvas.create_window((0, 0), window=scrollable_content, anchor="nw")
			canvas.configure(yscrollcommand=scrollbar.set)
			
			# Determine frame accessibility
			current_active_frame = bowler.current_frame
			last_frame_with_balls = None
			
			for i in range(9, -1, -1):
				if i < len(bowler.frames) and bowler.frames[i].balls:
					last_frame_with_balls = i
					break
			
			logger.info(f"SCORE_CORRECTION: Bowler {bowler.name} - Active frame: {current_active_frame}, Last with balls: {last_frame_with_balls}")
			
			# Create frame buttons in a proper grid (2 rows of 5)
			frames_grid = tk.Frame(scrollable_content, bg='black')
			frames_grid.pack(padx=20, pady=20, expand=True, fill=tk.BOTH)
			
			for i in range(10):
				row = i // 5
				col = i % 5
				
				frame = bowler.frames[i] if i < len(bowler.frames) else None
				
				if frame:
					frame_has_balls = bool(frame.balls)
					is_active_frame = (i == current_active_frame)
					is_last_with_balls = (i == last_frame_with_balls)
					is_accessible = frame_has_balls or is_active_frame
					
					btn_state = tk.NORMAL if is_accessible else tk.DISABLED
					
					# Enhanced styling
					if is_active_frame and frame_has_balls:
						bg_color = "green"
						frame_text = f"Frame {i+1}\n(ACTIVE - {len(frame.balls)} balls)"
					elif is_active_frame:
						bg_color = "darkgreen"
						frame_text = f"Frame {i+1}\n(ACTIVE - EMPTY)"
					elif is_last_with_balls:
						bg_color = "blue"
						frame_text = f"Frame {i+1}\n({len(frame.balls)} balls)"
					elif frame_has_balls:
						bg_color = "darkblue"
						frame_text = f"Frame {i+1}\n({len(frame.balls)} balls)"
					else:
						bg_color = "gray"
						frame_text = f"Frame {i+1}\n(EMPTY)"
					
					# Add frame info for better visibility
					if frame.balls:
						balls_info = ", ".join([f"{ball.symbol}({ball.value})" for ball in frame.balls])
						frame_text += f"\nBalls: {balls_info}"
						if hasattr(frame, 'total') and frame.total > 0:
							frame_text += f"\nTotal: {frame.total}"
				else:
					btn_state = tk.DISABLED
					bg_color = "black"
					frame_text = f"Frame {i+1}\n(N/A)"
				
				# Create button with proper command handling
				btn = tk.Button(
					frames_grid,
					text=frame_text,
					state=btn_state,
					command=lambda idx=i, last=(i == last_frame_with_balls), active=(i == current_active_frame): 
						self._select_frame_for_correction(idx, is_last=last, is_active=active),
					font=("Arial", 12, "bold"),
					bg=bg_color,
					fg="white",
					width=18,
					height=6,
					wraplength=140,
					relief="raised",
					bd=3
				)
				btn.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")
			
			# Configure grid weights for proper spacing
			for i in range(5):
				frames_grid.columnconfigure(i, weight=1, minsize=150)
			for i in range(2):
				frames_grid.rowconfigure(i, weight=1, minsize=100)
			
			# Pack the scrollable area
			canvas.pack(side="left", fill="both", expand=True)
			scrollbar.pack(side="right", fill="y")
			
			# Legend at bottom
			legend_frame = tk.Frame(content_container, bg='black')
			legend_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(20, 0))
			
			legend_text = ("GREEN = Active Frame  |  BLUE = Has balls  |  "
						  "GRAY = Empty  |  Click frame to edit balls")
			tk.Label(
				legend_frame, 
				text=legend_text,
				bg='black', 
				fg="gray", 
				font=("Arial", 14)
			).pack()
			
		except Exception as e:
			logger.error(f"Error selecting bowler: {str(e)}")
			tk.messagebox.showerror("Error", "Failed to select bowler")
	
	def _select_frame_for_correction(self, frame_idx, is_last=False, is_active=False):
		""" Select a frame for score correction using the main content area properly."""
		try:
			if frame_idx >= len(self.selected_bowler.frames):
				logger.error(f"Frame index {frame_idx} out of range for bowler {self.selected_bowler.name}")
				return
			
			frame = self.selected_bowler.frames[frame_idx]
			self.selected_frame = frame_idx
			
			logger.info(f"SCORE_CORRECTION: Selected frame {frame_idx+1} for {self.selected_bowler.name}")
			
			# Enable Clear Frame button for frames with balls OR active frames
			if hasattr(self, 'clear_frame_btn'):
				can_clear = (is_last and frame.balls) or (is_active and frame.balls)
				self.clear_frame_btn.config(state=tk.NORMAL if can_clear else tk.DISABLED)
				logger.info(f"Clear button {'enabled' if can_clear else 'disabled'} for frame {frame_idx+1}")
			
			# Clear content frame and rebuild with frame details
			for widget in self.content_frame.winfo_children():
				widget.destroy()
			
			# Create main details container
			details_container = tk.Frame(self.content_frame, bg='black')
			details_container.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)
			
			# Header section
			header_frame = tk.Frame(details_container, bg='black')
			header_frame.pack(fill=tk.X, pady=(0, 20))
			
			# Back to bowler selection button
			back_btn = tk.Button(
				header_frame,
				text="← Back to Bowler Selection",
				command=lambda: self._select_bowler_for_correction(self.selected_bowler),
				font=("Arial", 12),
				bg="gray",
				fg="white"
			)
			back_btn.pack(side=tk.LEFT)
			
			# Frame info header
			frame_status = "ACTIVE FRAME" if is_active else "COMPLETED FRAME"
			frame_info = f"Frame {frame_idx + 1} - {frame_status}"
			if frame.balls:
				frame_info += f" ({len(frame.balls)} balls)"
			
			info_label = tk.Label(
				header_frame,
				text=frame_info,
				bg='black',
				fg="cyan",
				font=("Arial", 18, "bold")
			)
			info_label.pack(side=tk.RIGHT)
			
			# Scrollable ball editing section
			canvas = tk.Canvas(details_container, bg='black', highlightthickness=0)
			scrollbar = tk.Scrollbar(details_container, orient="vertical", command=canvas.yview)
			scrollable_balls = tk.Frame(canvas, bg='black')
			
			scrollable_balls.bind(
				"<Configure>",
				lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
			)
			
			canvas.create_window((0, 0), window=scrollable_balls, anchor="nw")
			canvas.configure(yscrollcommand=scrollbar.set)
			
			# Ball editing section title
			balls_title = tk.Label(
				scrollable_balls,
				text="BALL EDITOR",
				bg='black',
				fg='yellow',
				font=("Arial", 16, "bold")
			)
			balls_title.pack(pady=(0, 15))
			
			# Show existing balls and allow adding new balls
			max_balls = 3  # Canadian 5-pin allows up to 3 balls per frame
			
			for ball_idx in range(max_balls):
				ball_frame = tk.Frame(scrollable_balls, bg='darkgray', relief='solid', bd=2)
				ball_frame.pack(fill=tk.X, pady=8, padx=20)
				
				# Ball header
				ball_header = tk.Frame(ball_frame, bg='darkgray')
				ball_header.pack(fill=tk.X, pady=8, padx=8)
				
				if ball_idx < len(frame.balls):
					# Existing ball - show details and allow editing
					ball = frame.balls[ball_idx]
					ball_title = f"Ball {ball_idx+1}: {ball.symbol} (Value: {ball.value})"
					btn_bg = "darkgreen"
					btn_state = tk.NORMAL
					
					# Show pin configuration
					pins_info = "Pins: " + ", ".join([
						f"L2({ball.pin_config[0]})",
						f"L3({ball.pin_config[1]})", 
						f"C5({ball.pin_config[2]})",
						f"R3({ball.pin_config[3]})",
						f"R2({ball.pin_config[4]})"
					])
					
					tk.Label(
						ball_header,
						text=pins_info,
						bg='darkgray',
						fg='white',
						font=("Arial", 10)
					).pack(anchor=tk.W)
					
				else:
					# New ball slot - allow adding
					ball_title = f"Ball {ball_idx+1}: (Empty - Click to add)"
					btn_bg = "darkred"
					btn_state = tk.NORMAL  # Allow adding new balls
				
				ball_btn = tk.Button(
					ball_header,
					text=ball_title,
					command=lambda idx=ball_idx: self._edit_ball_in_correction(idx),
					font=("Arial", 14, "bold"),
					bg=btn_bg,
					fg="white",
					state=btn_state,
					height=2
				)
				ball_btn.pack(fill=tk.X, pady=2)
			
			# Pack the scrollable area
			canvas.pack(side="left", fill="both", expand=True)
			scrollbar.pack(side="right", fill="y")
			
			# Frame totals display at bottom
			totals_frame = tk.Frame(details_container, bg='black')
			totals_frame.pack(fill=tk.X, pady=(15, 0))
			
			if hasattr(frame, 'total') and frame.total > 0:
				total_text = f"Frame Total: {frame.total}"
			else:
				current_total = sum(ball.value for ball in frame.balls) if frame.balls else 0
				total_text = f"Current Ball Total: {current_total}"
			
			tk.Label(
				totals_frame,
				text=total_text,
				bg='black',
				fg="yellow",
				font=("Arial", 18, "bold")
			).pack()
			
			# Frame status indicators
			status_parts = []
			if hasattr(frame, 'is_strike') and frame.is_strike:
				status_parts.append("STRIKE")
			if hasattr(frame, 'is_spare') and frame.is_spare:
				status_parts.append("SPARE")
			if not status_parts and frame.balls:
				status_parts.append("OPEN")
			
			if status_parts:
				tk.Label(
					totals_frame,
					text=" | ".join(status_parts),
					bg='black',
					fg="orange",
					font=("Arial", 14)
				).pack()
			
		except Exception as e:
			logger.error(f"Error selecting frame: {str(e)}")
			tk.messagebox.showerror("Error", "Failed to select frame")
	
	def _edit_ball_in_correction(self, ball_idx):
		""" Edit or add a ball with proper pin image sizing."""
		try:
			frame = self.selected_bowler.frames[self.selected_frame]
			
			# Clear the content frame for ball editing interface
			for widget in self.content_frame.winfo_children():
				widget.destroy()
			
			# Create main editing container
			edit_container = tk.Frame(self.content_frame, bg='black')
			edit_container.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)
			
			# Header with navigation
			header_frame = tk.Frame(edit_container, bg='black')
			header_frame.pack(fill=tk.X, pady=(0, 20))
			
			# Back button
			back_btn = tk.Button(
				header_frame,
				text="← Back to Frame",
				command=lambda: self._select_frame_for_correction(
					self.selected_frame,
					is_last=(self.selected_frame == self._get_last_frame_with_balls()),
					is_active=(self.selected_frame == self.selected_bowler.current_frame)
				),
				font=("Arial", 12),
				bg="gray",
				fg="white"
			)
			back_btn.pack(side=tk.LEFT)
			
			# Header text
			if ball_idx < len(frame.balls):
				header_text = f"EDITING Ball {ball_idx+1} in Frame {self.selected_frame+1}"
				current_ball = frame.balls[ball_idx]
			else:
				header_text = f"ADDING Ball {ball_idx+1} to Frame {self.selected_frame+1}"
				current_ball = None
			
			tk.Label(
				header_frame,
				text=header_text,
				bg='black',
				fg='yellow',
				font=("Arial", 18, "bold")
			).pack(side=tk.RIGHT)
			
			# Calculate correct pin state for this ball
			if ball_idx == 0:
				initial_pin_state = [0, 0, 0, 0, 0]  # All pins up (0 = up, 1 = down)
			else:
				initial_pin_state = [0, 0, 0, 0, 0]
				for i in range(ball_idx):
					if i < len(frame.balls):
						for pin_idx, pin in enumerate(frame.balls[i].pin_config):
							if pin == 1:
								initial_pin_state[pin_idx] = 1
			
			# If editing existing ball, show what THIS ball specifically did
			if current_ball:
				ball_contribution = current_ball.pin_config
				display_pin_state = initial_pin_state.copy()
				for pin_idx, pin in enumerate(ball_contribution):
					if pin == 1:
						display_pin_state[pin_idx] = 1
			else:
				display_pin_state = initial_pin_state.copy()
				ball_contribution = [0, 0, 0, 0, 0]
			
			# Store state for editing
			self.editing_pin_state = display_pin_state.copy()
			self.initial_pin_state = initial_pin_state.copy()
			
			# Pin editing interface
			pins_container = tk.Frame(edit_container, bg='black')
			pins_container.pack(pady=20, expand=True)
			
			# Instructions
			instruction_text = (
				"Click pins to toggle them. "
				f"{'Modify what this ball knocked down.' if current_ball else 'Select which pins this ball knocks down.'}"
			)
			tk.Label(
				pins_container,
				text=instruction_text,
				bg='black',
				fg='white',
				font=("Arial", 14)
			).pack(pady=(0, 20))
			
			# Pin display frame
			pins_frame = tk.Frame(pins_container, bg='black')
			pins_frame.pack()
			
			# Canadian 5-pin layout: lTwo(2), lThree(3), cFive(5), rThree(3), rTwo(2)
			pin_info = [
				("Left 2", 2, 0),
				("Left 3", 3, 1),
				("Center 5", 5, 2),
				("Right 3", 3, 3),
				("Right 2", 2, 4)
			]
			
			self.pin_edit_buttons = []
			
			for col, (name, value, pin_idx) in enumerate(pin_info):
				pin_container = tk.Frame(pins_frame, bg='black')
				pin_container.grid(row=0, column=col, padx=20, pady=15)
				
				# Pin button with proper image sizing
				current_image = self.pin_down_image if self.editing_pin_state[pin_idx] else self.pin_up_image
				
				# Ensure images are loaded and have proper size
				if not hasattr(self, 'pin_up_image') or not hasattr(self, 'pin_down_image'):
					logger.warning("Pin images not loaded, using text buttons")
					# Fallback to text buttons
					btn_text = "DOWN" if self.editing_pin_state[pin_idx] else "UP"
					btn_bg = "red" if self.editing_pin_state[pin_idx] else "green"
					
					btn = tk.Button(
						pin_container,
						text=btn_text,
						command=lambda idx=pin_idx: self._toggle_pin_in_ball_edit(idx),
						bd=3,
						relief="raised",
						bg=btn_bg,
						fg="white",
						width=8,
						height=4,
						font=("Arial", 12, "bold")
					)
				else:
					# Proper image button with consistent sizing
					btn = tk.Button(
						pin_container,
						image=current_image,
						command=lambda idx=pin_idx: self._toggle_pin_in_ball_edit(idx),
						bd=3,
						relief="raised",
						bg='white',
						# Remove width/height constraints to let image determine size
						compound=tk.CENTER
					)
					# CRITICAL: Keep image reference to prevent garbage collection
					btn.image = current_image
				
				btn.pack()
				self.pin_edit_buttons.append(btn)
				
				# Pin info
				state_text = "DOWN" if self.editing_pin_state[pin_idx] else "UP"
				color = "red" if self.editing_pin_state[pin_idx] else "green"
				
				tk.Label(
					pin_container,
					text=f"{name}\nValue: {value}\n{state_text}",
					bg='black',
					fg=color,
					font=("Arial", 12, "bold"),
					justify=tk.CENTER
				).pack(pady=(10, 0))
			
			# Current value display
			self.value_display = tk.Label(
				pins_container,
				text=self._calculate_ball_value_display(),
				bg='black',
				fg='yellow',
				font=("Arial", 16, "bold"),
				justify=tk.CENTER
			)
			self.value_display.pack(pady=(30, 0))
			
			# Action buttons at bottom
			action_frame = tk.Frame(edit_container, bg='black')
			action_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(30, 0))
			
			# Configure action frame grid
			action_frame.grid_columnconfigure(0, weight=1)
			action_frame.grid_columnconfigure(1, weight=1)
			action_frame.grid_columnconfigure(2, weight=1)
			
			# Delete ball button (only for existing balls)
			if current_ball:
				delete_btn = tk.Button(
					action_frame,
					text="DELETE THIS BALL",
					command=lambda: self._delete_ball_in_correction(ball_idx),
					font=("Arial", 14, "bold"),
					bg="darkred",
					fg="white",
					height=2
				)
				delete_btn.grid(row=0, column=0, padx=5, sticky="ew")
			
			# Save ball button
			save_ball_btn = tk.Button(
				action_frame,
				text="SAVE BALL" if current_ball else "ADD BALL",
				command=lambda: self._save_ball_in_correction_with_flags(ball_idx),
				font=("Arial", 14, "bold"),
				bg="green",
				fg="white",
				height=2
			)
			save_ball_btn.grid(row=0, column=1, padx=5, sticky="ew")
			
			# Cancel button
			cancel_btn = tk.Button(
				action_frame,
				text="CANCEL",
				command=lambda: self._select_frame_for_correction(
					self.selected_frame,
					is_last=(self.selected_frame == self._get_last_frame_with_balls()),
					is_active=(self.selected_frame == self.selected_bowler.current_frame)
				),
				font=("Arial", 14, "bold"),
				bg="blue",
				fg="white",
				height=2
			)
			cancel_btn.grid(row=0, column=2, padx=5, sticky="ew")
			
		except Exception as e:
			logger.error(f"Error editing ball: {str(e)}")
			tk.messagebox.showerror("Error", "Failed to edit ball")
	
	def _toggle_pin_in_ball_edit(self, pin_idx):
		""" Toggle pin state with proper image updating."""
		try:
			# Toggle the pin state
			self.editing_pin_state[pin_idx] ^= 1
			
			# Update button image or text depending on button type
			if hasattr(self, 'pin_up_image') and hasattr(self, 'pin_down_image'):
				# Image button update
				new_image = self.pin_down_image if self.editing_pin_state[pin_idx] else self.pin_up_image
				self.pin_edit_buttons[pin_idx].config(image=new_image)
				self.pin_edit_buttons[pin_idx].image = new_image
			else:
				# Text button update
				btn_text = "DOWN" if self.editing_pin_state[pin_idx] else "UP"
				btn_bg = "red" if self.editing_pin_state[pin_idx] else "green"
				self.pin_edit_buttons[pin_idx].config(text=btn_text, bg=btn_bg)
			
			# Update value display
			self.value_display.config(text=self._calculate_ball_value_display())
			
			logger.info(f"Toggled pin {pin_idx}, new state: {self.editing_pin_state}")
			
		except Exception as e:
			logger.error(f"Error toggling pin: {str(e)}")
	
	def _calculate_ball_value_display(self):
		"""Calculate and format the current ball value for display."""
		try:
			# Calculate what pins this ball knocked down (difference from initial state)
			ball_pins = [0, 0, 0, 0, 0]
			for i in range(5):
				if self.editing_pin_state[i] == 1 and self.initial_pin_state[i] == 0:
					ball_pins[i] = 1  # This ball knocked down this pin
			
			# Calculate value using pin values [2, 3, 5, 3, 2]
			pin_values = [2, 3, 5, 3, 2]
			ball_value = sum(a * b for a, b in zip(ball_pins, pin_values))
			
			# Format display
			knocked_pins = []
			for i, pin in enumerate(ball_pins):
				if pin == 1:
					pin_names = ["Left 2", "Left 3", "Center 5", "Right 3", "Right 2"]
					knocked_pins.append(pin_names[i])
			
			if knocked_pins:
				display = f"Ball Value: {ball_value}\nKnocked: {', '.join(knocked_pins)}"
			else:
				display = f"Ball Value: {ball_value}\nKnocked: No pins"
			
			return display
			
		except Exception as e:
			logger.error(f"Error calculating ball value: {str(e)}")
			return "Ball Value: Error"
			
	def _was_frame_originally_complete(self, frame, ball_idx):
		"""Determine if the frame was originally considered complete before this correction."""
		try:
			# For Canadian 5-pin, a frame is complete if:
			# 1. Strike on first ball (except 10th frame)
			# 2. Spare on second ball (except 10th frame)  
			# 3. Three balls thrown (any frame)
			# 4. 10th frame special rules
			
			is_10th_frame = (self.selected_frame == 9)
			
			if not is_10th_frame:
				# Regular frames (1-9)
				if len(frame.balls) >= 3:
					return True  # Three balls = complete
				elif len(frame.balls) >= 1 and frame.balls[0].value == 15:
					return True  # Strike = complete
				elif len(frame.balls) >= 2:
					total = frame.balls[0].value + frame.balls[1].value
					return total == 15  # Spare = complete
			else:
				# 10th frame - always requires 3 balls unless open after 2
				if len(frame.balls) >= 3:
					return True
				elif len(frame.balls) == 2:
					first_ball = frame.balls[0].value
					second_ball = frame.balls[1].value
					# Complete if no strike/spare in first two balls
					return first_ball < 15 and (first_ball + second_ball) < 15
			
			return False
			
		except Exception as e:
			logger.error(f"Error determining original completion: {e}")
			return False
		
	def _handle_correction_flags_before_ball(self, bowler):
		""" Handle correction flags before processing a ball."""
		try:
			if hasattr(bowler, 'correction_flags'):
				current_frame_idx = bowler.current_frame
				if current_frame_idx in bowler.correction_flags:
					flag_info = bowler.correction_flags[current_frame_idx]
					if flag_info.get('needs_continuation', False):
						logger.info(f"CORRECTION_CONTINUATION: Frame {current_frame_idx+1} continuing after correction")
						logger.info(f"Correction reason: {flag_info.get('reason', 'Unknown')}")
						
						# Don't clear the flag immediately - let the frame complete naturally
						# The flag will be cleared when the frame actually completes
						
						# Show a message to indicate correction continuation
						if hasattr(self.parent, 'set_scroll_message'):
							self.parent.set_scroll_message(f"Continuing corrected frame {current_frame_idx+1} for {bowler.name}")
						
						# CRITICAL: Set a flag to indicate this frame is in correction mode
						if not hasattr(bowler, 'frame_correction_active'):
							bowler.frame_correction_active = {}
						bowler.frame_correction_active[current_frame_idx] = True
						
						logger.info(f"CORRECTION_ACTIVE: Frame {current_frame_idx+1} marked as actively being corrected")
		
		except Exception as e:
			logger.error(f"Error handling correction flags: {e}")
			
	def _analyze_correction_context(self):
		""" Analyze correction context before making changes."""
		try:
			context = {
				'current_bowler_affected': False,
				'current_frame_affected': False,
				'affected_bowler_name': None,
				'affected_frame_idx': None,
				'current_bowler_idx': getattr(self, 'current_bowler_index', None),
				'selected_bowler_name': getattr(self.selected_bowler, 'name', None) if hasattr(self, 'selected_bowler') else None,
				'selected_frame_idx': getattr(self, 'selected_frame', None)
			}
			
			# Check if we're correcting the current bowler
			if (hasattr(self, 'current_bowler_index') and 
				hasattr(self, 'selected_bowler') and
				self.current_bowler_index < len(self.bowlers)):
				
				current_bowler = self.bowlers[self.current_bowler_index]
				
				if current_bowler == self.selected_bowler:
					context['current_bowler_affected'] = True
					context['affected_bowler_name'] = current_bowler.name
					
					# Check if we're correcting the current frame
					if (hasattr(self, 'selected_frame') and 
						self.selected_frame == current_bowler.current_frame):
						context['current_frame_affected'] = True
						context['affected_frame_idx'] = self.selected_frame
			
			logger.info(f"CORRECTION_CONTEXT: {context}")
			return context
			
		except Exception as e:
			logger.error(f"Error analyzing correction context: {e}")
			return {
				'current_bowler_affected': False,
				'current_frame_affected': False,
				'affected_bowler_name': None,
				'affected_frame_idx': None
			}
	
	def _show_correction_success_with_options_fixed(self, context):
		""" Show success message with pin restoration option based on context."""
		try:
			# Create success popup
			success_popup = tk.Toplevel(self.frame)
			success_popup.title("Score Correction Saved")
			success_popup.geometry("500x350")
			success_popup.configure(bg="darkgreen")
			success_popup.attributes("-topmost", True)
			success_popup.grab_set()
			
			# Center the popup
			success_popup.transient(self.frame)
			success_popup.update_idletasks()
			width = success_popup.winfo_width()
			height = success_popup.winfo_height()
			x = (success_popup.winfo_screenwidth() // 2) - (width // 2)
			y = (success_popup.winfo_screenheight() // 2) - (height // 2)
			success_popup.geometry(f'{width}x{height}+{x}+{y}')
			
			# Main container
			main_frame = tk.Frame(success_popup, bg="darkgreen")
			main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
			
			# Success message
			tk.Label(
				main_frame,
				text="✓ SCORE CORRECTIONS SAVED!",
				bg="darkgreen",
				fg="white",
				font=("Arial", 18, "bold")
			).pack(pady=(0, 10))
			
			tk.Label(
				main_frame,
				text="Game display has been updated with corrected scores",
				bg="darkgreen",
				fg="white",
				font=("Arial", 12)
			).pack(pady=(0, 20))
			
			# Show correction details
			if context.get('affected_bowler_name'):
				tk.Label(
					main_frame,
					text=f"Corrected: {context['affected_bowler_name']}, Frame {context.get('affected_frame_idx', 0) + 1}",
					bg="darkgreen",
					fg="yellow",
					font=("Arial", 12, "bold")
				).pack(pady=(0, 10))
			
			# Pin restoration option based on context
			current_bowler_affected = context.get('current_bowler_affected', False)
			current_frame_affected = context.get('current_frame_affected', False)
			
			logger.info(f"PIN_RESTORE_CHECK: current_bowler_affected={current_bowler_affected}, current_frame_affected={current_frame_affected}")
			
			if current_bowler_affected and current_frame_affected:
				tk.Label(
					main_frame,
					text="The current bowler's active frame was modified!",
					bg="darkgreen",
					fg="yellow",
					font=("Arial", 12, "bold")
				).pack(pady=(0, 10))
				
				tk.Label(
					main_frame,
					text="Would you like to set the pins to match the corrected state?",
					bg="darkgreen",
					fg="white",
					font=("Arial", 11)
				).pack(pady=(0, 15))
				
				# Pin restoration button
				pin_restore_btn = tk.Button(
					main_frame,
					text="SET PINS TO MATCH CORRECTION",
					command=lambda: self._restore_pins_after_correction_fixed(success_popup, context),
					font=("Arial", 12, "bold"),
					bg="orange",
					fg="white",
					height=2
				)
				pin_restore_btn.pack(fill=tk.X, pady=5)
				
				# Skip pin restoration button
				skip_pin_btn = tk.Button(
					main_frame,
					text="SKIP PIN RESTORATION",
					command=success_popup.destroy,
					font=("Arial, 10"),
					bg="gray",
					fg="white",
					height=1
				)
				skip_pin_btn.pack(fill=tk.X, pady=2)
				
			else:
				logger.info("PIN_RESTORE_SKIP: Not current bowler's current frame, no pin restoration needed")
				
				# Show why no pin restoration
				if context.get('affected_bowler_name'):
					current_bowler_name = self.bowlers[self.current_bowler_index].name if hasattr(self, 'current_bowler_index') and self.current_bowler_index < len(self.bowlers) else "Unknown"
					
					if not current_bowler_affected:
						reason_text = f"Corrected {context['affected_bowler_name']}, but current bowler is {current_bowler_name}"
					else:
						reason_text = "Corrected a completed frame, not the active frame"
					
					tk.Label(
						main_frame,
						text=reason_text,
						bg="darkgreen",
						fg="lightgray",
						font=("Arial", 10)
					).pack(pady=(0, 10))
			
			# Close button
			close_btn = tk.Button(
				main_frame,
				text="CLOSE",
				command=success_popup.destroy,
				font=("Arial", 12, "bold"),
				bg="white",
				fg="darkgreen",
				height=2
			)
			close_btn.pack(fill=tk.X, pady=(10, 0))
			
			# Auto-close after 15 seconds if no pin restoration needed
			if not (current_bowler_affected and current_frame_affected):
				success_popup.after(15000, success_popup.destroy)
			
		except Exception as e:
			logger.error(f"Error showing correction success: {e}")
			
	
	def _restore_pins_after_correction_fixed(self, popup, context):
		""" Restore pins to match the corrected frame state."""
		try:
			popup.destroy()
			
			# Get current bowler and frame using context
			current_bowler_idx = context.get('current_bowler_idx')
			affected_frame_idx = context.get('affected_frame_idx')
			
			if current_bowler_idx is None or affected_frame_idx is None:
				logger.error("PIN_RESTORE_ERROR: Missing context information")
				tk.messagebox.showerror("Pin Restore Error", "Cannot determine which frame to restore pins for")
				return
			
			current_bowler = self.bowlers[current_bowler_idx]
			current_frame = current_bowler.frames[affected_frame_idx]
			
			logger.info(f"PIN_RESTORE: Restoring pins for {current_bowler.name}, Frame {affected_frame_idx + 1}")
			
			# Calculate pin state after all balls in corrected frame
			pin_state = [0, 0, 0, 0, 0]  # Start with all pins up
			
			for ball in current_frame.balls:
				for pin_idx, pin_knocked in enumerate(ball.pin_config):
					if pin_knocked == 1:
						pin_state[pin_idx] = 1  # Pin is down
			
			logger.info(f"PIN_RESTORE: Calculated pin state: {pin_state}")
			
			# Convert to machine control format (1 = up, 0 = down)
			machine_control = {
				'lTwo': 0 if pin_state[0] == 1 else 1,
				'lThree': 0 if pin_state[1] == 1 else 1,
				'cFive': 0 if pin_state[2] == 1 else 1,
				'rThree': 0 if pin_state[3] == 1 else 1,
				'rTwo': 0 if pin_state[4] == 1 else 1
			}
			
			logger.info(f"PIN_RESTORE_CORRECTION: Setting pins to match corrected state: {machine_control}")
			
			# Send pin set command
			if hasattr(self, 'parent') and hasattr(self.parent, 'handle_pin_set'):
				self.parent.handle_pin_set(machine_control)
				logger.info("PIN_RESTORE: Command sent via parent.handle_pin_set")
			else:
				# Fallback: use dispatcher
				from event_dispatcher import dispatcher
				if 'pin_set' in dispatcher.listeners:
					dispatcher.listeners['pin_set'][0](machine_control)
					logger.info("PIN_RESTORE: Command sent via dispatcher")
				else:
					logger.error("PIN_RESTORE: No pin_set handler available")
			
			# Show confirmation
			self._show_pin_restore_confirmation()
			
			logger.info("Pin restoration after correction completed")
			
		except Exception as e:
			logger.error(f"Error restoring pins after correction: {e}")
			tk.messagebox.showerror("Pin Restore Error", f"Failed to restore pins: {str(e)}")
	
	def _show_pin_restore_confirmation(self):
		"""Show confirmation that pins were restored."""
		try:
			confirmation_popup = tk.Toplevel(self.frame)
			confirmation_popup.title("Pins Restored")
			confirmation_popup.geometry("400x200")
			confirmation_popup.configure(bg="blue")
			confirmation_popup.attributes("-topmost", True)
			
			# Center the popup
			confirmation_popup.transient(self.frame)
			confirmation_popup.update_idletasks()
			width = confirmation_popup.winfo_width()
			height = confirmation_popup.winfo_height()
			x = (confirmation_popup.winfo_screenwidth() // 2) - (width // 2)
			y = (confirmation_popup.winfo_screenheight() // 2) - (height // 2)
			confirmation_popup.geometry(f'{width}x{height}+{x}+{y}')
			
			tk.Label(
				confirmation_popup,
				text="✓ PINS SET TO MATCH\nCORRECTED STATE",
				bg="blue",
				fg="white",
				font=("Arial", 16, "bold"),
				justify=tk.CENTER
			).pack(expand=True, pady=20)
			
			tk.Label(
				confirmation_popup,
				text="The physical pins now match the corrected ball results.\nYou can continue playing from this state.",
				bg="blue",
				fg="white",
				font=("Arial", 12),
				justify=tk.CENTER
			).pack(expand=True, pady=10)
			
			# Manual close button
			tk.Button(
				confirmation_popup,
				text="OK",
				command=confirmation_popup.destroy,
				font=("Arial", 12, "bold"),
				bg="white",
				fg="blue"
			).pack(pady=10)
			
			# Auto-close after 5 seconds
			confirmation_popup.after(5000, confirmation_popup.destroy)
			
		except Exception as e:
			logger.error(f"Error showing pin restore confirmation: {e}")
	
	def _show_correction_success_with_options(self, current_bowler_affected, current_frame_affected):
		"""Show success message with pin restoration option."""
		try:
			# Create success popup
			success_popup = tk.Toplevel(self.frame)
			success_popup.title("Score Correction Saved")
			success_popup.geometry("500x300")
			success_popup.configure(bg="darkgreen")
			success_popup.attributes("-topmost", True)
			success_popup.grab_set()
			
			# Center the popup
			success_popup.transient(self.frame)
			success_popup.update_idletasks()
			width = success_popup.winfo_width()
			height = success_popup.winfo_height()
			x = (success_popup.winfo_screenwidth() // 2) - (width // 2)
			y = (success_popup.winfo_screenheight() // 2) - (height // 2)
			success_popup.geometry(f'{width}x{height}+{x}+{y}')
			
			# Main container
			main_frame = tk.Frame(success_popup, bg="darkgreen")
			main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
			
			# Success message
			tk.Label(
				main_frame,
				text="✓ SCORE CORRECTIONS SAVED!",
				bg="darkgreen",
				fg="white",
				font=("Arial", 18, "bold")
			).pack(pady=(0, 10))
			
			tk.Label(
				main_frame,
				text="Game display has been updated with corrected scores",
				bg="darkgreen",
				fg="white",
				font=("Arial", 12)
			).pack(pady=(0, 20))
			
			# Conditional pin restoration option
			if current_bowler_affected and current_frame_affected:
				tk.Label(
					main_frame,
					text="The current bowler's active frame was modified.",
					bg="darkgreen",
					fg="yellow",
					font=("Arial", 12, "bold")
				).pack(pady=(0, 10))
				
				tk.Label(
					main_frame,
					text="Would you like to set the pins to match the corrected state?",
					bg="darkgreen",
					fg="white",
					font=("Arial", 11)
				).pack(pady=(0, 15))
				
				# Pin restoration button
				pin_restore_btn = tk.Button(
					main_frame,
					text="SET PINS TO MATCH CORRECTION",
					command=lambda: self._restore_pins_after_correction(success_popup),
					font=("Arial", 12, "bold"),
					bg="orange",
					fg="white",
					height=2
				)
				pin_restore_btn.pack(fill=tk.X, pady=5)
			
			# Close button
			close_btn = tk.Button(
				main_frame,
				text="CLOSE",
				command=success_popup.destroy,
				font=("Arial", 12, "bold"),
				bg="white",
				fg="darkgreen",
				height=2
			)
			close_btn.pack(fill=tk.X, pady=(10, 0))
			
			# Auto-close after 10 seconds if no pin restoration needed
			if not (current_bowler_affected and current_frame_affected):
				success_popup.after(10000, success_popup.destroy)
			
		except Exception as e:
			logger.error(f"Error showing correction success: {e}")
	
	def _restore_pins_after_correction(self, popup):
		"""Restore pins to match the corrected frame state."""
		try:
			popup.destroy()
			
			# Get current bowler and frame
			current_bowler = self.bowlers[self.current_bowler_index]
			current_frame_idx = current_bowler.current_frame
			current_frame = current_bowler.frames[current_frame_idx]
			
			# Calculate pin state after all balls in current frame
			pin_state = [0, 0, 0, 0, 0]  # Start with all pins up
			
			for ball in current_frame.balls:
				for pin_idx, pin_knocked in enumerate(ball.pin_config):
					if pin_knocked == 1:
						pin_state[pin_idx] = 1  # Pin is down
			
			# Convert to machine control format (1 = up, 0 = down)
			machine_control = {
				'lTwo': 0 if pin_state[0] == 1 else 1,
				'lThree': 0 if pin_state[1] == 1 else 1,
				'cFive': 0 if pin_state[2] == 1 else 1,
				'rThree': 0 if pin_state[3] == 1 else 1,
				'rTwo': 0 if pin_state[4] == 1 else 1
			}
			
			logger.info(f"PIN_RESTORE_CORRECTION: Setting pins to match corrected state: {machine_control}")
			
			# Send pin set command
			if hasattr(self, 'parent') and hasattr(self.parent, 'handle_pin_set'):
				self.parent.handle_pin_set(machine_control)
			else:
				# Fallback: use dispatcher
				from event_dispatcher import dispatcher
				if 'pin_set' in dispatcher.listeners:
					dispatcher.listeners['pin_set'][0](machine_control)
			
			# Show confirmation
			confirmation_popup = tk.Toplevel(self.frame)
			confirmation_popup.title("Pins Restored")
			confirmation_popup.geometry("300x150")
			confirmation_popup.configure(bg="blue")
			confirmation_popup.attributes("-topmost", True)
			
			tk.Label(
				confirmation_popup,
				text="✓ PINS SET TO MATCH\nCORRECTED STATE",
				bg="blue",
				fg="white",
				font=("Arial", 14, "bold"),
				justify=tk.CENTER
			).pack(expand=True)
			
			# Auto-close after 3 seconds
			confirmation_popup.after(3000, confirmation_popup.destroy)
			
			logger.info("Pin restoration after correction completed")
			
		except Exception as e:
			logger.error(f"Error restoring pins after correction: {e}")
			tk.messagebox.showerror("Pin Restore Error", f"Failed to restore pins: {str(e)}")
	
	def _is_frame_complete_after_correction(self, frame, bowler):
		"""Determine if frame should be complete after correction."""
		try:
			is_10th_frame = (self.selected_frame == 9)
			
			if not is_10th_frame:
				# Regular frames
				if len(frame.balls) >= 3:
					return True
				elif len(frame.balls) >= 1 and frame.balls[0].value == 15:
					return True  # Strike
				elif len(frame.balls) >= 2:
					total = frame.balls[0].value + frame.balls[1].value
					return total == 15  # Spare
			else:
				# 10th frame
				if len(frame.balls) >= 3:
					return True
				elif len(frame.balls) == 2:
					first_ball = frame.balls[0].value
					second_ball = frame.balls[1].value
					return first_ball < 15 and (first_ball + second_ball) < 15
			
			return False
			
		except Exception as e:
			logger.error(f"Error determining completion after correction: {e}")
			return False
	
	def _mark_frame_for_continuation(self, bowler, frame_idx):
		"""Mark a frame to continue play when it's the bowler's turn."""
		try:
			# Add correction flag to the bowler
			if not hasattr(bowler, 'correction_flags'):
				bowler.correction_flags = {}
			
			bowler.correction_flags[frame_idx] = {
				'needs_continuation': True,
				'corrected_at': time.time(),
				'reason': 'Frame completion changed during correction'
			}
			
			# If this is the current frame and current bowler, handle immediately
			if (frame_idx == bowler.current_frame and 
				hasattr(self, 'current_bowler_index') and
				self.bowlers[self.current_bowler_index] == bowler):
				
				logger.info(f"IMMEDIATE_CONTINUATION: Frame {frame_idx+1} continuation needed for current bowler")
				# Don't advance the frame - let them continue playing
				
			logger.info(f"CORRECTION_FLAG: Frame {frame_idx+1} marked for continuation")
			
		except Exception as e:
			logger.error(f"Error marking frame for continuation: {e}")
	
	def _delete_ball_in_correction(self, ball_idx):
		"""Delete a ball from the frame."""
		try:
			frame = self.selected_bowler.frames[self.selected_frame]
			
			if ball_idx < len(frame.balls):
				deleted_ball = frame.balls.pop(ball_idx)
				logger.info(f"Deleted ball {ball_idx+1} ({deleted_ball.symbol}) from frame {self.selected_frame+1}")
				
				# Recalculate frame status
				self._recalculate_frame_status(frame)
				
				# Recalculate all scores
				self._calculate_all_scores(self.selected_bowler)
				
				# Return to frame view
				content_frame = None
				for widget in self.score_correction_window.winfo_children():
					for child in widget.winfo_children():
						if isinstance(child, tk.Frame) and child.winfo_children():
							for subchild in child.winfo_children():
								if isinstance(subchild, tk.Frame) and len(subchild.winfo_children()) > 1:
									content_frame = subchild.winfo_children()[-1]
									break
							if content_frame:
								break
					if content_frame:
						break
				
				if content_frame:
					self._select_frame_for_correction(
						self.selected_frame, content_frame,
						is_last=(self.selected_frame == self._get_last_frame_with_balls()),
						is_active=(self.selected_frame == self.selected_bowler.current_frame)
					)
			else:
				logger.warning(f"Cannot delete ball {ball_idx+1} - does not exist")
				
		except Exception as e:
			logger.error(f"Error deleting ball: {str(e)}")
			tk.messagebox.showerror("Error", f"Failed to delete ball: {str(e)}")
	
	def _recalculate_frame_status(self, frame):
		"""FIXED: Recalculate strike/spare status for a frame with proper spare detection."""
		try:
			frame.is_strike = False
			frame.is_spare = False
			
			if not frame.balls:
				return
			
			# Check for strike (first ball = 15) - ONLY on first ball
			if len(frame.balls) >= 1 and frame.balls[0].value == 15:
				frame.is_strike = True
				logger.info("Frame recalculated as STRIKE")
				return  # Strike cannot also be spare
			
			# Check for spare (first two balls = 15, but NOT a strike)
			if len(frame.balls) >= 2:
				total_first_two = frame.balls[0].value + frame.balls[1].value
				if total_first_two == 15:
					frame.is_spare = True
					logger.info("Frame recalculated as SPARE")
					return
			
			logger.info(f"Frame status: Strike={frame.is_strike}, Spare={frame.is_spare}")
			
		except Exception as e:
			logger.error(f"Error recalculating frame status: {str(e)}")
	
	def _get_last_frame_with_balls(self):
		"""Get the index of the last frame that has balls."""
		for i in range(9, -1, -1):
			if i < len(self.selected_bowler.frames) and self.selected_bowler.frames[i].balls:
				return i
		return None
	
	def _close_score_correction(self):
		""" Properly close the score correction window with cleanup."""
		try:
			if hasattr(self, 'score_correction_window'):
				# Clear any editing state
				if hasattr(self, 'editing_pin_state'):
					delattr(self, 'editing_pin_state')
				if hasattr(self, 'initial_pin_state'):
					delattr(self, 'initial_pin_state')
				if hasattr(self, 'pin_edit_buttons'):
					delattr(self, 'pin_edit_buttons')
				if hasattr(self, 'value_display'):
					delattr(self, 'value_display')
				
				# Clear selection state
				self.selected_bowler = None
				self.selected_frame = None
				self.selected_ball = None
				
				# Release grab and destroy window
				self.score_correction_window.grab_release()
				self.score_correction_window.destroy()
				delattr(self, 'score_correction_window')
				
				logger.info("Score correction window closed successfully")
				
		except Exception as e:
			logger.error(f"Error closing score correction window: {str(e)}")
	
	# Additional helper methods for frame accessibility
	
	def _is_frame_accessible_for_correction(self, bowler, frame_idx):
		"""Determine if a frame is accessible for correction."""
		if frame_idx >= len(bowler.frames):
			return False
		
		frame = bowler.frames[frame_idx]
		current_active_frame = bowler.current_frame
		
		# Frame is accessible if:
		# 1. It has balls, OR
		# 2. It's the current active frame
		return bool(frame.balls) or (frame_idx == current_active_frame)
	
	def _get_frame_correction_status(self, bowler, frame_idx):
		"""Get the status of a frame for correction purposes."""
		if frame_idx >= len(bowler.frames):
			return "invalid", "N/A", "black"
		
		frame = bowler.frames[frame_idx]
		current_active_frame = bowler.current_frame
		
		if frame_idx == current_active_frame:
			if frame.balls:
				return "active_with_balls", f"ACTIVE ({len(frame.balls)} balls)", "green"
			else:
				return "active_empty", "ACTIVE (Empty)", "darkgreen"
		elif frame.balls:
			last_frame_with_balls = self._get_last_frame_with_balls_for_bowler(bowler)
			if frame_idx == last_frame_with_balls:
				return "last_with_balls", f"Last ({len(frame.balls)} balls)", "blue"
			else:
				return "has_balls", f"{len(frame.balls)} balls", "darkblue"
		else:
			return "empty", "Empty", "gray"
	
	def _get_last_frame_with_balls_for_bowler(self, bowler):
		"""Get the index of the last frame with balls for a specific bowler."""
		for i in range(9, -1, -1):
			if i < len(bowler.frames) and bowler.frames[i].balls:
				return i
		return None
	
	# DEBUGGING: Enhanced logging for score correction
	def _log_correction_state(self, operation, bowler_name=None, frame_idx=None, ball_idx=None):
		"""Enhanced logging for debugging score correction issues."""
		try:
			log_msg = f"SCORE_CORRECTION_{operation}:"
			
			if bowler_name:
				log_msg += f" Bowler={bowler_name}"
			if frame_idx is not None:
				log_msg += f" Frame={frame_idx+1}"
			if ball_idx is not None:
				log_msg += f" Ball={ball_idx+1}"
			
			if bowler_name and hasattr(self, 'bowlers'):
				bowler = next((b for b in self.bowlers if b.name == bowler_name), None)
				if bowler and frame_idx is not None and frame_idx < len(bowler.frames):
					frame = bowler.frames[frame_idx]
					log_msg += f" FrameBalls={len(frame.balls)}"
					log_msg += f" FrameTotal={getattr(frame, 'total', 0)}"
					log_msg += f" BowlerTotal={bowler.total_score}"
			
			logger.info(log_msg)
			
		except Exception as e:
			logger.error(f"Error in correction logging: {str(e)}")
	
	def _clear_selected_frame(self):
		"""Clear the currently selected frame after confirmation."""
		if not self.selected_bowler or self.selected_frame is None:
			return
		
		bowler = self.selected_bowler
		frame = bowler.frames[self.selected_frame]
		
		# Create frame balls summary for confirmation message
		balls_summary = []
		for i, ball in enumerate(frame.balls):
			if hasattr(ball, 'symbol') and ball.symbol != "-":
				balls_summary.append(f"Ball {i+1}: {ball.symbol}")
			else:
				balls_summary.append(f"Ball {i+1}: {ball.value}")
		
		# Confirmation message
		message = f"Are you sure you want to clear frame {self.selected_frame + 1} for {bowler.name}?\n\n"
		message += "Current values:\n"
		message += "\n".join(balls_summary)
		message += f"\n\nFrame Total: {frame.total}"
		
		# Show confirmation dialog
		self.show_confirmation_dialog(
			"Confirm Clear Frame", 
			message,
			lambda: self._perform_clear_frame(bowler, self.selected_frame)
		)
	
	def _perform_clear_frame(self, bowler, frame_idx):
		"""Actually perform the frame clearing after confirmation."""
		# Reset the frame
		frame = bowler.frames[frame_idx]
		frame.balls = []
		frame.total = 0
		frame.is_strike = False
		frame.is_spare = False
		
		# Recalculate scores
		self._calculate_all_scores(bowler)
		
		# Reset pins
		self.reset_pins()
		
		# Update the UI
		content_frame = None
		for widget in self.score_correction_window.winfo_children():
			if widget not in (self.score_correction_window.winfo_children()[0], self.score_correction_window.winfo_children()[-1]):
				content_frame = widget
				break
		
		if content_frame:
			self._select_bowler_for_correction(bowler, content_frame)
		
		# Show confirmation
		tk.messagebox.showinfo("Frame Cleared", f"Frame {frame_idx + 1} has been cleared for {bowler.name}")
		
		self.update_ui()
		
	def _request_machine_status(self, data=None):
		"""Request current machine status through dispatcher."""
		if 'request_machine_status' in dispatcher.listeners:
			dispatcher.listeners['request_machine_status'][0]({})
	
	def revert_last_ball(self):
		"""ENHANCED: Revert the last ball with proper multi-frame turn handling"""
		if not self.game_started:
			logger.info("Cannot revert: Game not started")
			return
		
		# Find the last ball thrown across all bowlers
		last_ball_info = self._find_last_ball_thrown()
		
		if not last_ball_info:
			logger.info("No balls to revert in the game")
			return
		
		bowler_idx, frame_idx, ball_idx, bowler, frame, last_ball = last_ball_info
		
		# Create confirmation message
		message = "Are you sure you want to revert the last ball?\n\n"
		message += f"Bowler: {bowler.name}\n"
		message += f"Frame: {frame_idx + 1}\n"
		message += f"Ball: {ball_idx + 1}\n"
		if hasattr(last_ball, 'symbol') and last_ball.symbol != "-":
			message += f"Last ball: {last_ball.symbol}\n"
		else:
			message += f"Last ball: {last_ball.value}\n"
		
		# Show confirmation dialog
		self.show_confirmation_dialog(
			"Confirm Revert Last Ball", 
			message,
			lambda: self._perform_revert_last_ball(bowler_idx, frame_idx, ball_idx, bowler, frame)
		)
	
	def _find_last_ball_thrown(self):
		"""ENHANCED: Find the last ball with better timestamp tracking"""
		last_ball_info = None
		latest_game_position = -1
		
		for bowler_idx, bowler in enumerate(self.bowlers):
			for frame_idx, frame in enumerate(bowler.frames):
				if frame.balls:
					for ball_idx, ball in enumerate(frame.balls):
						# Enhanced position calculation that considers multi-frame turns
						game_position = self._calculate_game_position(bowler_idx, frame_idx, ball_idx)
						
						if game_position > latest_game_position:
							latest_game_position = game_position
							last_ball_info = (bowler_idx, frame_idx, ball_idx, bowler, frame, ball)
		
		return last_ball_info
	
	def _calculate_game_position(self, bowler_idx, frame_idx, ball_idx):
		"""Calculate the chronological position of a ball in the game"""
		# For multi-frame turns, we need to calculate based on completed turns
		frames_per_turn = self.settings.frames_per_turn
		
		# Calculate which "turn" this frame belongs to
		turn_number = frame_idx // frames_per_turn
		frame_in_turn = frame_idx % frames_per_turn
		
		# Position calculation: (turn * bowlers * frames_per_turn * 3) + (bowler * frames_per_turn * 3) + (frame_in_turn * 3) + ball
		position = (turn_number * len(self.bowlers) * frames_per_turn * 3) + \
				  (bowler_idx * frames_per_turn * 3) + \
				  (frame_in_turn * 3) + \
				  ball_idx
		
		return position
	

	
	def _calculate_pin_state_after_revert(self, target_frame, target_ball_idx):
		"""Calculate what pin state should be after removing the target ball"""
		pins_should_be = {'lTwo': 1, 'lThree': 1, 'cFive': 1, 'rThree': 1, 'rTwo': 1}
		
		# Apply all balls BEFORE the reverted ball
		for i in range(target_ball_idx):
			ball = target_frame.balls[i]
			for pin_idx, pin_knocked in enumerate(ball.pin_config):
				if pin_knocked == 1:
					pin_names = ['lTwo', 'lThree', 'cFive', 'rThree', 'rTwo']
					pins_should_be[pin_names[pin_idx]] = 0
		
		return pins_should_be
	
	def _recalculate_frame_status_after_revert(self, frame):
		"""Recalculate frame status after ball removal"""
		frame.is_strike = False
		frame.is_spare = False
		
		if not frame.balls:
			return
		
		# Check for strike (first ball = 15)
		if len(frame.balls) >= 1 and frame.balls[0].value == 15:
			frame.is_strike = True
			return
		
		# Check for spare (first two balls = 15, but not strike)
		if len(frame.balls) >= 2:
			total_first_two = frame.balls[0].value + frame.balls[1].value
			if total_first_two == 15:
				frame.is_spare = True
	
	def _determine_correct_game_state_after_revert(self, target_bowler_idx, target_frame_idx, target_ball_idx, target_bowler, target_frame):
		"""ENHANCED: Determine correct game state considering multi-frame turns"""
		frames_per_turn = self.settings.frames_per_turn
		
		# Determine if the frame was previously complete
		was_frame_complete = self._was_frame_complete_before_revert(target_frame, target_ball_idx)
		
		# Calculate the correct current frame for the target bowler
		if target_ball_idx == 0 and target_frame_idx > 0:
			# Reverting first ball of a frame - go back to previous frame
			correct_current_frame = target_frame_idx - 1
			needs_full_reset = True  # Usually need reset when going back to previous frame
		else:
			# Reverting within current frame
			correct_current_frame = target_frame_idx
			needs_full_reset = False
		
		# Determine correct current bowler based on multi-frame turn logic
		if frames_per_turn == 1:
			# Traditional bowling - each bowler bowls one frame at a time
			correct_bowler_index = target_bowler_idx
		else:
			# Multi-frame turns - need to determine if we're still in the same turn
			turn_number = target_frame_idx // frames_per_turn
			frame_in_turn = target_frame_idx % frames_per_turn
			
			if target_ball_idx == 0 and frame_in_turn == 0 and target_frame_idx > 0:
				# Reverting first ball of first frame in a turn - go to previous bowler's turn
				previous_turn = turn_number - 1
				if previous_turn >= 0:
					# Find the bowler who was bowling in the previous turn
					previous_bowler_idx = (target_bowler_idx - 1) % len(self.bowlers)
					correct_bowler_index = previous_bowler_idx
					correct_current_frame = (previous_turn + 1) * frames_per_turn - 1  # Last frame of previous turn
					needs_full_reset = True
				else:
					# First turn, first frame - stay with current bowler
					correct_bowler_index = target_bowler_idx
			else:
				# Within the same turn
				correct_bowler_index = target_bowler_idx
		
		return {
			'bowler_index': correct_bowler_index,
			'current_frame': correct_current_frame,
			'needs_full_reset': needs_full_reset
		}
	
	def _was_frame_complete_before_revert(self, frame, ball_idx):
		"""Check if frame was complete before the ball being reverted"""
		if ball_idx == 0:
			return False  # First ball, frame wasn't complete
		
		# Check if frame would be complete with balls up to but not including the reverted ball
		remaining_balls = frame.balls[:ball_idx]
		
		if not remaining_balls:
			return False
		
		# Check completion conditions
		if len(remaining_balls) >= 1 and remaining_balls[0].value == 15:
			return True  # Strike
		
		if len(remaining_balls) >= 2:
			total = remaining_balls[0].value + remaining_balls[1].value
			if total == 15:
				return True  # Spare
			# Two balls but no spare - frame would continue to third ball
			return False
		
		return False
	
	def _select_ball_for_correction(self, ball_idx, content_frame):
		"""Select a ball for correction and show pin states after this ball."""
		logger.info("Selected ball for correction with pin state display")
		try:
			frame = self.selected_bowler.frames[self.selected_frame]
			ball = frame.balls[ball_idx]
			self.selected_ball = ball
			
			# Clear pins area
			for widget in content_frame.winfo_children():
				if widget.winfo_y() > 100:  # Keep frame and ball buttons
					widget.destroy()
			
			# Calculate pin state AFTER this ball
			pin_state_after_ball = [0, 0, 0, 0, 0]  # Start with all pins up
			
			# Apply all balls up to and including the selected ball
			for i in range(ball_idx + 1):
				if i < len(frame.balls):
					ball_pin_config = frame.balls[i].pin_config
					for pin_idx, pin_knocked in enumerate(ball_pin_config):
						if pin_knocked == 1:  # This ball knocked down this pin
							pin_state_after_ball[pin_idx] = 1  # Pin is now down
			
			logger.info(f"Pin state after ball {ball_idx + 1}: {pin_state_after_ball}")
			
			# Pin buttons frame
			pins_frame = tk.Frame(content_frame)
			pins_frame.pack(pady=20)
			
			# Info label showing what we're displaying
			info_label = tk.Label(
				pins_frame,
				text=f"Pin state AFTER Ball {ball_idx + 1} (Click to edit THIS ball's result)",
				font=("Arial", 12, "bold"),
				fg="blue"
			)
			info_label.pack(pady=(0, 10))
			
			# Pin display frame
			pin_display_frame = tk.Frame(pins_frame)
			pin_display_frame.pack()
			
			# Use your existing pin images
			pin_up_img = getattr(self, 'pin_up_image', None)
			pin_down_img = getattr(self, 'pin_down_image', None)
			
			# Create pin buttons - Canadian 5-pin order: lTwo, lThree, cFive, rThree, rTwo
			pin_positions = [
				("Left 2", 2, 0),
				("Left 3", 3, 1), 
				("Center 5", 5, 2),
				("Right 3", 3, 3),
				("Right 2", 2, 4)
			]
			
			for col, (name, value, pin_idx) in enumerate(pin_positions):
				pin_frame = tk.Frame(pin_display_frame)
				pin_frame.grid(row=0, column=col, padx=10)
				
				# Show current pin state (what it looks like after this ball)
				current_pin_state = pin_state_after_ball[pin_idx]
				current_image = pin_down_img if current_pin_state else pin_up_img
				
				# Create button that shows current ball's contribution
				btn = tk.Button(
					pin_frame,
					image=current_image,
					command=lambda idx=pin_idx: self._toggle_pin_in_correction(idx, content_frame),
					bd=2,
					relief="raised"
				)
				btn.image = current_image  # Keep reference
				btn.pack()
				
				# Pin value label with state info
				state_text = "DOWN" if current_pin_state else "UP"
				color = "red" if current_pin_state else "green"
				
				tk.Label(
					pin_frame, 
					text=f"{name}\nValue: {value}\n{state_text}",
					font=("Arial", 10),
					fg=color
				).pack()
			
			# Ball contribution info
			ball_info_frame = tk.Frame(content_frame)
			ball_info_frame.pack(pady=20)
			
			# Show what THIS ball specifically did
			this_ball_contribution = ball.pin_config
			pins_knocked_by_this_ball = []
			for i, knocked in enumerate(this_ball_contribution):
				if knocked == 1:
					pins_knocked_by_this_ball.append(pin_positions[i][0])
			
			contribution_text = f"Ball {ball_idx + 1} knocked down: "
			if pins_knocked_by_this_ball:
				contribution_text += ", ".join(pins_knocked_by_this_ball)
			else:
				contribution_text += "No pins"
			
			tk.Label(
				ball_info_frame,
				text=contribution_text,
				font=("Arial", 11, "bold"),
				fg="purple"
			).pack()
			
			# Current ball value and frame total
			tk.Label(
				ball_info_frame, 
				text=f"Ball Value: {ball.value} | Frame Total: {frame.total}",
				font=("Arial", 14)
			).pack()
			
		except Exception as e:
			logger.error(f"Error selecting ball: {str(e)}")
			tk.messagebox.showerror("Error", "Failed to select ball for editing")
			
	def _toggle_pin_in_correction(self, pin_index, content_frame):
		"""Toggle pin state during correction using your existing image handling."""
		if not self.selected_ball:
			return
		
		# Toggle pin state (using your existing logic)
		self.selected_ball.pin_config[pin_index] ^= 1  # Toggle between 0 and 1
		
		# Recalculate ball value using your existing pin values
		pin_values = [2, 3, 5, 3, 2]
		self.selected_ball.value = sum(
			a * b for a, b in zip(self.selected_ball.pin_config, pin_values))
		
		# Update the symbol based on new pin configuration
		pin_config_str = ''.join(str(pin) for pin in self.selected_ball.pin_config)
		self.selected_ball.symbol = self.settings.patterns.get(pin_config_str, '-')
		
		# Recalculate frame total
		frame = self.selected_bowler.frames[self.selected_frame]
		frame.total = sum(ball.value for ball in frame.balls)
		
		# Recalculate all scores
		self._calculate_all_scores(self.selected_bowler)
		
		# Refresh the display to show changes
		ball_idx = frame.balls.index(self.selected_ball)
		self._select_ball_for_correction(ball_idx, content_frame)
		

	def open_bowler_status(self):
		"""Open the bowler status window."""
		self.status_window = tk.Toplevel(self.frame)
		self.status_window.title("Bowler Status")
		self.status_window.geometry("600x400")
		
		# Main container
		main_frame = tk.Frame(self.status_window)
		main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
		
		# Headers
		headers = ["Bowler", "Active", "Absent", "Pre-Bowl"]
		for col, header in enumerate(headers):
			tk.Label(main_frame, text=header, font=("Arial", 14, "bold")).grid(row=0, column=col, padx=10, pady=5)
		
		# Bowler status rows
		self.status_vars = []
		for row, bowler in enumerate(self.bowlers, start=1):
			# Bowler name
			tk.Label(main_frame, text=bowler.name, font=("Arial", 12)).grid(row=row, column=0, sticky="w", padx=10)
			
			# Status radio buttons
			status_var = tk.StringVar(value="active")
			self.status_vars.append((bowler, status_var))
			
			for col, status in enumerate(["active", "absent", "prebowl"], start=1):
				rb = tk.Radiobutton(
					main_frame,
					variable=status_var,
					value=status,
					command=lambda b=bowler, s=status: self._update_bowler_status(b, s)
				)
				rb.grid(row=row, column=col)
		
		# Save button
		tk.Button(
			self.status_window,
			text="SAVE",
			command=self._save_bowler_status,
			font=("Arial", 14),
			bg="green",
			fg="white"
		).pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=10)
	
	def _update_bowler_status(self, bowler, status):
		"""Update bowler status immediately when radio button changes."""
		if status == "absent":
			# Set all frames to 0
			for frame in bowler.frames:
				frame.balls = []
				frame.total = 0
				frame.is_strike = False
				frame.is_spare = False
			bowler.total_score = 0
		elif status == "prebowl":
			# Check server for pre-bowl scores or use default 15 per frame
			# This is a placeholder - implement actual server check
			for frame in bowler.frames:
				if not frame.balls:  # Only if frame not already played
					frame.balls = [BallResult([0,0,1,0,0], "15", 15)]  # Default 15 points
					frame.total = 15
			self._calculate_all_scores(bowler)
		
		self.update_ui()
	
	def _save_bowler_status(self):
		"""Save bowler status changes."""
		for bowler, status_var in self.status_vars:
			self._update_bowler_status(bowler, status_var.get())
		self.status_window.destroy()
		
	def _safe_open_pin_set(self):
		"""Safely open pin set window with error handling."""
		try:
			self._close_settings()  # Close settings window first
			self.open_pin_set()
		except Exception as e:
			logger.error(f"Error opening pin set: {str(e)}")
			tk.messagebox.showerror("Error", "Failed to open pin set window")
	
	def open_pin_set(self):
		"""Open the pin set window to manually set pin states."""
		if hasattr(self, 'pin_set_window') and self.pin_set_window and self.pin_set_window.winfo_exists():
			self.pin_set_window.lift()
			return
		
		self.pin_set_window = tk.Toplevel(self.frame)
		self.pin_set_window.title("Pin Set")
		self.pin_set_window.geometry('1500x750')
		self.pin_set_window.after(10, self.pin_set_window.wm_attributes, '-fullscreen', 'true')
		self.pin_set_window.attributes("-fullscreen", True)
		self.pin_set_window.protocol("WM_DELETE_WINDOW", self._close_pin_set)
		
		# Make it modal
		self.pin_set_window.grab_set()
		self.pin_set_window.focus_set()
		
		# Initialize current pin state to all up by default
		self.current_pin_state = [0, 0, 0, 0, 0]  # All pins up (UI representation)
		
		# Request machine status and initialize UI after a short delay
		if 'request_machine_status' in dispatcher.listeners and dispatcher.listeners['request_machine_status']:
			dispatcher.listeners['request_machine_status'][0]({})
			# Schedule UI initialization after status request
			self.pin_set_window.after(200, self._initialize_pin_set_ui)
		else:
			# Immediate initialization with default state
			self._initialize_pin_set_ui()
	
	def _initialize_pin_set_ui(self):
		"""Initialize the pin set UI after receiving machine status."""
		# Check if window still exists
		if not hasattr(self, 'pin_set_window') or not self.pin_set_window or not self.pin_set_window.winfo_exists():
			return
		
		# Clear any existing widgets to prevent duplication
		for widget in self.pin_set_window.winfo_children():
			widget.destroy()
		
		# Update current pin state from machine status if available
		if hasattr(self, 'machine_status') and self.machine_status:
			machine_control = self.machine_status.get('control', {})
			# Convert machine control to UI state (invert values)
			# Machine: 1 = up, 0 = down
			# UI: 0 = up, 1 = down
			self.current_pin_state = [
				0 if machine_control.get('lTwo', 1) == 1 else 1,
				0 if machine_control.get('lThree', 1) == 1 else 1,
				0 if machine_control.get('cFive', 1) == 1 else 1,
				0 if machine_control.get('rThree', 1) == 1 else 1,
				0 if machine_control.get('rTwo', 1) == 1 else 1
			]
			logger.info(f"PIN_SET: Updated pin state from machine: {self.current_pin_state}")
		
		try:
			# Create main container
			main_frame = tk.Frame(self.pin_set_window, bg=self.settings.background_color)
			main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
			
			# Title label
			title_label = tk.Label(
				main_frame,
				text="Set Pin Configuration",
				bg=self.settings.background_color,
				fg=self.settings.foreground_color,
				font=("Arial", 24, "bold")
			)
			title_label.pack(pady=(0, 30))
			
			# Pin display frame
			pin_frame = tk.Frame(main_frame, bg=self.settings.background_color)
			pin_frame.pack(pady=20)
			
			# Pin positions with values: lTwo, lThree, cFive, rThree, rTwo
			pin_positions = [
				("Left 2", 2, 0),
				("Left 3", 3, 1), 
				("Center 5", 5, 2),
				("Right 3", 3, 3),
				("Right 2", 2, 4)
			]
			
			# Create pin buttons
			self.pin_buttons = []
			for col, (name, value, pin_idx) in enumerate(pin_positions):
				pin_container = tk.Frame(pin_frame, bg=self.settings.background_color)
				pin_container.grid(row=0, column=col, padx=20, pady=10)
				
				# Create pin button with correct initial image based on current state
				current_image = self.pin_down_image if self.current_pin_state[pin_idx] == 1 else self.pin_up_image
				btn = tk.Button(
					pin_container,
					image=current_image,
					command=lambda idx=pin_idx: self._toggle_pin_in_set(idx),
					bd=2,
					relief="raised"
				)
				btn.image = current_image  # Keep reference
				btn.pack()
				self.pin_buttons.append(btn)
				
				# Pin name and value label
				info_label = tk.Label(
					pin_container,
					text=f"{name}\nValue: {value}",
					bg=self.settings.background_color,
					fg=self.settings.foreground_color,
					font=("Arial", 14, "bold")
				)
				info_label.pack(pady=(10, 0))
			
			# Status label to show pin configuration
			self.pin_status_label = tk.Label(
				main_frame,
				text=self._get_pin_status_text(),
				bg=self.settings.background_color,
				fg="yellow",
				font=("Arial", 16, "bold")
			)
			self.pin_status_label.pack(pady=30)
			
			# Control buttons frame
			button_frame = tk.Frame(main_frame, bg=self.settings.background_color)
			button_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=20)
			
			# Reset All button (set all pins back to up)
			reset_btn = tk.Button(
				button_frame,
				text="RESET ALL PINS UP",
				bg="blue",
				fg="white",
				command=self._reset_all_pins_in_set,
				font=("Arial", 16, "bold")
			)
			reset_btn.pack(side=tk.LEFT, padx=10, expand=True, fill=tk.X)
			
			# Apply button to send pin configuration
			apply_btn = tk.Button(
				button_frame,
				text="APPLY PIN SET",
				bg="green",
				fg="white",
				command=self._apply_pin_set,
				font=("Arial", 16, "bold")
			)
			apply_btn.pack(side=tk.LEFT, padx=10, expand=True, fill=tk.X)
			
			# Close button
			close_btn = tk.Button(
				button_frame,
				text="CLOSE",
				bg="red",
				fg="white",
				command=self._close_pin_set,
				font=("Arial", 16, "bold")
			)
			close_btn.pack(side=tk.LEFT, padx=10, expand=True, fill=tk.X)
			
			logger.info("PIN_SET: UI initialized successfully")
			
		except Exception as e:
			logger.error(f"Error creating pin set UI: {str(e)}")
			self._close_pin_set()
			tk.messagebox.showerror("Error", "Failed to create pin set window")
	
	def _get_pin_status_text(self):
		"""Get status text describing current pin configuration."""
		down_pins = sum(self.current_pin_state)
		total_value = 0
		
		# Calculate total value of pins that are down
		pin_values = [2, 3, 5, 3, 2]
		for i, (is_down, value) in enumerate(zip(self.current_pin_state, pin_values)):
			if is_down:
				total_value += value
		
		if down_pins == 0:
			return "All pins are UP - Score: 0"
		elif down_pins == 5:
			return "All pins are DOWN - Score: 15 (STRIKE!)"
		else:
			return f"{down_pins} pins DOWN - Score: {total_value}"
	
	def _toggle_pin_in_set(self, pin_index):
		"""Toggle pin state in the pin set window."""
		# Toggle pin state (0 = up, 1 = down)
		self.current_pin_state[pin_index] ^= 1
		
		# Update button image
		if self.current_pin_state[pin_index] == 1:
			self.pin_buttons[pin_index].config(image=self.pin_down_image)
			self.pin_buttons[pin_index].image = self.pin_down_image
		else:
			self.pin_buttons[pin_index].config(image=self.pin_up_image)
			self.pin_buttons[pin_index].image = self.pin_up_image
		
		# Update status label
		self.pin_status_label.config(text=self._get_pin_status_text())
		
		logger.info(f"PIN_SET: Toggled pin {pin_index}, new state: {self.current_pin_state}")
	
	def _reset_all_pins_in_set(self):
		"""Knock down all pins and trigger machine cycle to reset them up."""
		logger.info("PIN_SET: Executing 'knock down all pins' operation")
		
		# Set all pins to DOWN state in UI (1 = down, 0 = up)
		self.current_pin_state = [1, 1, 1, 1, 1]
		
		# Update all button images to show pins down
		for i, btn in enumerate(self.pin_buttons):
			btn.config(image=self.pin_down_image)
			btn.image = self.pin_down_image
		
		# Update status label
		self.pin_status_label.config(text=self._get_pin_status_text())
		
		logger.info("PIN_SET: All pins set to DOWN in UI")
		
		# Prepare machine control data (machine: 0 = down, 1 = up)
		# UI state: 1 = down, so machine control should be 0 for all pins
		pin_control_data = {
			'lTwo': 0,	 # DOWN
			'lThree': 0,   # DOWN
			'cFive': 0,	# DOWN
			'rThree': 0,   # DOWN
			'rTwo': 0	  # DOWN
		}
		
		logger.info(f"PIN_SET: Setting machine control to knock down all pins: {pin_control_data}")
		
		try:
			# Send pin control data to machine
			if 'pin_set' in dispatcher.listeners and dispatcher.listeners['pin_set']:
				dispatcher.listeners['pin_set'][0](pin_control_data)
				logger.info("PIN_SET: Successfully sent knock down command to machine")
				
				# Schedule a follow-up reset to bring all pins back up after machine cycle
				def restore_pins_up():
					logger.info("PIN_SET: Scheduling follow-up reset to bring pins back up")
					if hasattr(self.parent, 'machine'):
						# Set all pins back to UP and do immediate reset
						self.parent.machine.control = {'lTwo': 1, 'lThree': 1, 'cFive': 1, 'rThree': 1, 'rTwo': 1}
						self.parent.machine._force_full_reset = True
						self.parent.machine.reset_pins()
						logger.info("PIN_SET: Follow-up reset completed - all pins should be up")
				
				# Schedule the follow-up after a delay to allow machine cycle to complete
				if hasattr(self, 'pin_set_window') and self.pin_set_window:
					self.pin_set_window.after(3000, restore_pins_up)  # 3 second delay
				
				# Update UI to show pins are back up
				def update_ui_pins_up():
					self.current_pin_state = [0, 0, 0, 0, 0]  # All pins up in UI
					for i, btn in enumerate(self.pin_buttons):
						btn.config(image=self.pin_up_image)
						btn.image = self.pin_up_image
					self.pin_status_label.config(text=self._get_pin_status_text())
					logger.info("PIN_SET: UI updated to show all pins up")
				
				# Update UI after machine cycle
				if hasattr(self, 'pin_set_window') and self.pin_set_window:
					self.pin_set_window.after(4000, update_ui_pins_up)  # 4 second delay
					
			else:
				logger.error("PIN_SET: No pin_set handler available")
				# Fallback to direct machine access
				if hasattr(self.parent, 'machine'):
					logger.info("PIN_SET: Using direct machine access as fallback")
					self.parent.machine.pin_restore(pin_control_data)
				else:
					logger.error("PIN_SET: No machine control method available")
		
		except Exception as e:
			logger.error(f"Error in knock down all pins operation: {e}")
		
		logger.info("PIN_SET: Knock down all pins operation completed")
	def _apply_pin_set(self):
		"""Apply the selected pin configuration to the machine using dispatcher."""
		try:
			# Log the pin configuration
			logger.info(f"PIN_SET: Applying pin configuration: {self.current_pin_state}")
			
			# For the machine control, 0 = pin down, 1 = pin up
			# In our UI, 0 = pin up, 1 = pin down
			# The pin names in the correct order for Canadian 5-pin: lTwo, lThree, cFive, rThree, rTwo
			pin_control_data = {
				'lTwo': 0 if self.current_pin_state[0] == 1 else 1,
				'lThree': 0 if self.current_pin_state[1] == 1 else 1,
				'cFive': 0 if self.current_pin_state[2] == 1 else 1,
				'rThree': 0 if self.current_pin_state[3] == 1 else 1,
				'rTwo': 0 if self.current_pin_state[4] == 1 else 1
			}
			
			# Log the individual pin states
			logger.info(f"PIN_SET: Pin control states to apply: {pin_control_data}")
			
			# Use proper event dispatcher to send pin_set event
			from event_dispatcher import dispatcher
			
			if 'pin_set' in dispatcher.listeners and dispatcher.listeners['pin_set']:
				# Send the control data through dispatcher
				dispatcher.listeners['pin_set'][0](pin_control_data)
				logger.info("PIN_SET: Command sent via dispatcher successfully")
				
				# Show success message and close window
				self._show_success_and_close("Pin configuration applied successfully!")
			else:
				logger.error("No pin_set handler available in dispatcher")
				
				# Try direct machine access as fallback
				if hasattr(self.parent, 'machine'):
					logger.info("PIN_SET: Using direct machine access as fallback")
					self.parent.machine.pin_restore(pin_control_data)
					self._show_success_and_close("Pin configuration applied via direct access!")
				else:
					tk.messagebox.showerror("Error", "No pin control method available")
			
		except Exception as e:
			logger.error(f"Error applying pin configuration: {str(e)}")
			tk.messagebox.showerror("Error", f"Failed to apply pin configuration: {str(e)}")
	def _show_success_and_close(self, message):
		"""Show success message and close the pin set window."""
		# Create a simple success popup that auto-closes
		success_popup = tk.Toplevel(self.pin_set_window)
		success_popup.title("Success")
		success_popup.geometry("400x150")
		success_popup.configure(bg="green")
		
		# Center the popup
		success_popup.transient(self.pin_set_window)
		success_popup.grab_set()
		
		# Success message
		tk.Label(
			success_popup,
			text=message,
			bg="green",
			fg="white",
			font=("Arial", 14, "bold"),
			wraplength=350
		).pack(expand=True)
		
		# Auto-close after 2 seconds and close pin set window
		def auto_close():
			try:
				success_popup.destroy()
			except:
				pass
			self._close_pin_set()
		
		success_popup.after(2000, auto_close)
	
	def _close_pin_set(self):
		"""Properly close the pin set window."""
		try:
			if hasattr(self, 'pin_set_window') and self.pin_set_window:
				self.pin_set_window.grab_release()
				self.pin_set_window.destroy()
				delattr(self, 'pin_set_window')
			
			# Clear pin set related attributes
			if hasattr(self, 'current_pin_state'):
				delattr(self, 'current_pin_state')
			if hasattr(self, 'pin_buttons'):
				delattr(self, 'pin_buttons')
			if hasattr(self, 'pin_status_label'):
				delattr(self, 'pin_status_label')
				
			logger.info("PIN_SET: Window closed successfully")
			
		except Exception as e:
			logger.error(f"Error closing pin set window: {str(e)}")
			
	def _handle_machine_status(self, status_data):
		"""Handle machine status response"""
		self.machine_status = status_data
		logger.info(f"[GAME] Received machine status: {status_data}")
		
		# If pin_set window is waiting for status, update it
		if hasattr(self, 'pin_set_window') and self.pin_set_window and self.pin_set_window.winfo_exists():
			logger.info("PIN_SET: Reinitializing UI with fresh machine status")
			# Don't reinitialize if UI is already built, just update status
			if hasattr(self, 'current_pin_state'):
				machine_control = status_data.get('control', {})
				self.current_pin_state = [
					0 if machine_control.get('lTwo', 1) == 1 else 1,
					0 if machine_control.get('lThree', 1) == 1 else 1,
					0 if machine_control.get('cFive', 1) == 1 else 1,
					0 if machine_control.get('rThree', 1) == 1 else 1,
					0 if machine_control.get('rTwo', 1) == 1 else 1
				]
				# Update UI elements if they exist
				if hasattr(self, 'pin_buttons') and hasattr(self, 'pin_status_label'):
					for i, btn in enumerate(self.pin_buttons):
						if self.current_pin_state[i] == 1:
							btn.config(image=self.pin_down_image)
							btn.image = self.pin_down_image
						else:
							btn.config(image=self.pin_up_image)
							btn.image = self.pin_up_image
					self.pin_status_label.config(text=self._get_pin_status_text())
					
	def _handle_frame_advancement(self, frame, bowler):
		"""Handle frame advancement logic"""
		if frame.is_strike and bowler.current_frame < 9:
			logger.info("ADVANCE_STRIKE: Advancing frame after strike")
			self._advance_frame(bowler)
		elif frame.is_spare and bowler.current_frame < 9:
			logger.info("ADVANCE_SPARE: Advancing frame after spare")
			self._advance_frame(bowler)
		elif len(frame.balls) == 3:
			if bowler.current_frame < 9:
				logger.info("ADVANCE_3BALLS: Advancing frame after 3 balls")
				self._advance_frame(bowler)
			else:
				logger.info("END_GAME: Ending bowler game after 10th frame")
				self._end_bowler_game(bowler)

	def pin_restore(self):
		"""Pin restore via settings - schedule pin restore operation"""
		if not self.game_started:
			logger.info("Cannot restore pins: Game has not started.")
			return

		logger.info("Pin restore requested")
		
		# Get current machine status for restore
		if hasattr(self, 'machine_status') and self.machine_status:
			pin_data = self.machine_status.get('control', {})
			
			# Schedule pin restore
			if 'schedule_pin_restore' in dispatcher.listeners:
				dispatcher.listeners['schedule_pin_restore'][0](pin_data)
			else:
				logger.error("No schedule_pin_restore handler available")
				
	def _save_enhanced_game_data(self):
		"""Save game data with enhanced tracking information."""
		game_record = {
			"game_number": self.current_game_number,
			"date": datetime.now().strftime("%Y-%m-%d"),
			"time": datetime.now().strftime("%H:%M:%S"),
			"display_mode": getattr(self.settings, 'display_mode', 'standard'),
			"bowlers": []
		}
		
		for bowler in self.bowlers:
			bowler_record = {
				"name": bowler.name,
				"frames": [],
				"total_score": bowler.total_score
			}
			
			for frame_idx, frame in enumerate(bowler.frames):
				if not frame.balls:
					continue
					
				frame_record = {
					"frame_number": frame_idx + 1,
					"balls": [],
					"total": frame.total,
					"is_strike": frame.is_strike,
					"is_spare": frame.is_spare
				}
				
				# Enhanced tracking data
				if getattr(self.settings, 'use_enhanced_tracking', False):
					frame_record["bonus_details"] = getattr(frame, 'bonus_details', {})
					
					for ball_idx, ball in enumerate(frame.balls):
						ball_record = {
							"ball_number": ball_idx + 1,
							"pin_config": ball.pin_config,
							"symbol": ball.symbol,
							"ball_value": ball.ball_value,
							"frame_running_total": ball.frame_running_total,
							"cumulative_total": ball.cumulative_total,
							"is_bonus_ball": ball.is_bonus_ball
						}
						frame_record["balls"].append(ball_record)
				else:
					# Standard tracking
					for ball_idx, ball in enumerate(frame.balls):
						ball_record = {
							"ball_number": ball_idx + 1,
							"pin_config": ball.pin_config,
							"symbol": ball.symbol,
							"value": ball.value
						}
						frame_record["balls"].append(ball_record)
				
				bowler_record["frames"].append(frame_record)
			
			game_record["bowlers"].append(bowler_record)
		
		self.game_data.append(game_record)
		self._save_to_database(game_record)
	
	# Method to switch display modes
	def set_display_mode(self, mode: str):
		"""Set the display mode for the game."""
		if not hasattr(self.settings, 'display_config'):
			self.settings.display_config = DisplayConfig()
		
		if mode == "standard":
			self.settings.display_config.set_standard_mode()
		elif mode == "detailed":
			self.settings.display_config.set_detailed_mode()
		elif mode == "simulation":
			self.settings.display_config.set_simulation_mode()
		
		# Apply settings to the game settings object
		self.settings.show_bonus_asterisk = self.settings.display_config.show_bonus_asterisk
		self.settings.show_frame_breakdown = self.settings.display_config.show_frame_breakdown
		self.settings.use_enhanced_tracking = self.settings.display_config.use_enhanced_tracking
		self.settings.display_mode = self.settings.display_config.display_mode
		
		logger.info(f"Display mode set to: {mode}")
		
		# Refresh UI if game is active
		if self.game_started:
			self.update_ui()

	def _calculate_strike_streak_total(self, bowler: Bowler, end_frame_idx: int) -> int:
		"""Calculate the total score for a completed strike streak."""
		streak_total = 0
		
		# Find the start of the current streak
		start_idx = end_frame_idx
		while start_idx > 0 and bowler.frames[start_idx - 1].is_strike:
			start_idx -= 1
		
		# Calculate total for all strikes in the streak
		for frame_idx in range(start_idx, end_frame_idx + 1):
			frame = bowler.frames[frame_idx]
			if frame.is_strike:
				base_value = sum(b.value for b in frame.balls)
				bonus = self._calculate_strike_bonus_across_bowlers(bowler, frame_idx)
				streak_total += base_value + bonus
		
		return streak_total

	def _safe_open_display_settings(self):
		"""Safely open display settings with error handling."""
		try:
			self._close_settings()  # Close settings window first
			self.open_display_settings()
		except Exception as e:
			logger.error(f"Error opening display settings: {e}")
			tk.messagebox.showerror("Error", "Failed to open display settings")

	def open_display_settings(self):
		"""Open combined display settings window."""
		if hasattr(self, 'display_settings_window') and self.display_settings_window.winfo_exists():
			self.display_settings_window.lift()
			return

		self.display_settings_window = tk.Toplevel(self.frame)
		self.display_settings_window.title("Display Settings")
		self.display_settings_window.geometry("600x500")
		self.display_settings_window.protocol("WM_DELETE_WINDOW", self._close_display_settings)
		
		# Make it modal
		self.display_settings_window.grab_set()
		self.display_settings_window.focus_set()
		
		# Title
		tk.Label(
			self.display_settings_window,
			text="Display Settings",
			font=("Arial", 16, "bold")
		).pack(pady=10)
		
		# Display Mode Section
		mode_frame = tk.LabelFrame(self.display_settings_window, text="Display Mode", font=("Arial", 12, "bold"))
		mode_frame.pack(fill=tk.X, padx=20, pady=10)
		
		self.display_mode_var = tk.StringVar(value=getattr(self.settings, 'display_mode', 'standard'))
		
		# Standard mode (default with bonus balls, optional detail indicators)
		tk.Radiobutton(
			mode_frame,
			text="Standard - Show bonus balls in frames (X 8 2)",
			variable=self.display_mode_var,
			value="standard",
			font=("Arial", 11)
		).pack(anchor=tk.W, padx=10, pady=2)
		
		# Detailed mode (all indicators and breakdowns)
		tk.Radiobutton(
			mode_frame,
			text="Detailed - Show bonus balls AND (15+8) breakdowns",
			variable=self.display_mode_var,
			value="detailed",
			font=("Arial", 11)
		).pack(anchor=tk.W, padx=10, pady=2)
		
		# Clean mode (no bonus indicators)
		tk.Radiobutton(
			mode_frame,
			text="Clean - No bonus indicators or breakdowns",
			variable=self.display_mode_var,
			value="clean",
			font=("Arial", 11)
		).pack(anchor=tk.W, padx=10, pady=2)
		
		# Display Options Section
		options_frame = tk.LabelFrame(self.display_settings_window, text="Display Options", font=("Arial", 12, "bold"))
		options_frame.pack(fill=tk.X, padx=20, pady=10)
		
		# Show bonus balls option (default ON)
		self.show_bonus_var = tk.BooleanVar(value=getattr(self.settings, 'show_bonus_in_frame', True))
		tk.Checkbutton(
			options_frame,
			text="Show bonus balls in earning frame (X 8 2) - Default ON",
			variable=self.show_bonus_var,
			font=("Arial", 11)
		).pack(anchor=tk.W, padx=10, pady=2)
		
		# Detail indicators option (asterisks) - DEFAULT OFF
		self.show_detail_var = tk.BooleanVar(value=getattr(self.settings, 'show_bonus_asterisk', False))
		tk.Checkbutton(
			options_frame,
			text="Show detail indicators (*) for bonus balls - Default OFF",
			variable=self.show_detail_var,
			font=("Arial", 11)
		).pack(anchor=tk.W, padx=10, pady=2)
		
		# Strike streak mode option
		self.strike_streak_var = tk.BooleanVar(value=getattr(self.settings, 'strike_streak_mode', False))
		tk.Checkbutton(
			options_frame,
			text="Strike Streak Mode (don't show totals until streak breaks)",
			variable=self.strike_streak_var,
			font=("Arial", 11)
		).pack(anchor=tk.W, padx=10, pady=2)
		
		# Description section
		desc_frame = tk.Frame(self.display_settings_window)
		desc_frame.pack(fill=tk.X, padx=20, pady=10)
		
		tk.Label(
			desc_frame,
			text="- Standard: Default mode with bonus balls shown in frames\n"
				 "- Detailed: Adds (15+8) score breakdowns\n"
				 "- Clean: Minimal display without bonus indicators\n"
				 "- Detail indicators: Add * symbols to bonus balls (DEFAULT OFF)\n"
				 "- Strike Streak: Hide strike totals until streak ends",
			font=("Arial", 9),
			fg="gray",
			justify=tk.LEFT
		).pack(anchor=tk.W, pady=2)
		
		# Buttons
		button_frame = tk.Frame(self.display_settings_window)
		button_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=10)
		
		tk.Button(
			button_frame,
			text="APPLY",
			command=self._apply_display_settings,
			font=("Arial", 12),
			bg="green",
			fg="white"
		).pack(side=tk.LEFT, padx=10, expand=True)
		
		tk.Button(
			button_frame,
			text="CLOSE",
			command=self._close_display_settings,
			font=("Arial", 12),
			bg="red",
			fg="white"
		).pack(side=tk.RIGHT, padx=10, expand=True)
	def _apply_display_settings(self):
		"""Apply the new combined display settings and render immediately."""
		# Apply display mode
		mode = self.display_mode_var.get()
		self.settings.display_mode = mode
		
		# Apply options
		self.settings.show_bonus_in_frame = self.show_bonus_var.get()
		self.settings.show_bonus_asterisk = self.show_detail_var.get()
		self.settings.strike_streak_mode = self.strike_streak_var.get()
		
		# Configure mode-specific settings
		if mode == "standard":
			self.settings.show_bonus_in_frame = True  # Always on for standard
			self.settings.show_frame_breakdown = False
		elif mode == "detailed":
			self.settings.show_bonus_in_frame = True  # Always on for detailed
			self.settings.show_frame_breakdown = True
			self.settings.show_bonus_asterisk = True  # Always on for detailed
		elif mode == "clean":
			self.settings.show_bonus_in_frame = False
			self.settings.show_bonus_asterisk = False
			self.settings.show_frame_breakdown = False
		
		logger.info(f"Display settings applied: mode={mode}, bonus_in_frame={self.settings.show_bonus_in_frame}, "
				   f"asterisk={self.settings.show_bonus_asterisk}, streak={self.settings.strike_streak_mode}")
		
		# ENHANCED UI UPDATE: Force complete re-initialization and update
		try:
			# Clear the current UI completely
			for widget in self.frame.winfo_children():
				widget.destroy()
			
			# Recreate UI manager with new settings
			self.ui_manager = GameUIManager(self.frame, self.bowlers, self.settings)
			self.ui_manager.set_button_callbacks(
				on_reset=self.reset_pins,
				on_skip=self.skip_bowler,
				on_hold=self.toggle_hold,
				on_settings=self.open_settings,
				on_pin_restore=self.pin_restore
			)
			
			# Recalculate scores with new settings
			for bowler in self.bowlers:
				self._calculate_all_scores(bowler)
			
			# Force complete UI re-render
			self.ui_manager.ui_initialized = False
			self.update_ui()
			
			logger.info("DISPLAY_SETTINGS: UI completely refreshed with new settings")
			
		except Exception as e:
			logger.error(f"Error updating UI after display settings change: {e}")
			# Fallback to basic update
			self.update_ui()
		
		self._close_display_settings()
		
	def _close_display_settings(self):
		"""Close display settings window."""
		if hasattr(self, 'display_settings_window'):
			try:
				self.display_settings_window.grab_release()
				self.display_settings_window.destroy()
			except:
				pass
			del self.display_settings_window

	def _schedule_immediate_full_reset(self, reason):
		"""Schedule and execute immediate full reset"""
		logger.info(f"IMMEDIATE_FULL_RESET: Executing immediate full reset for {reason}")
		
		# Execute reset immediately through machine
		if hasattr(self.parent, 'machine'):
			# Set the force flag and execute immediately
			self.parent.machine._force_full_reset = True
			self.parent.machine.reset_pins()
			logger.info("IMMEDIATE_FULL_RESET: Reset executed immediately")
		else:
			logger.error("No machine available for immediate full reset")
			
	def _start_next_game(self):

		logger.info("Starting next game")
		
		# Clean up countdown widgets
		if hasattr(self, 'next_game_button') and self.next_game_button:
			try:
				self.next_game_button.destroy()
			except:
				pass
			self.next_game_button = None
			
		if hasattr(self, 'next_game_container') and self.next_game_container:
			try:
				self.next_game_container.destroy()
			except:
				pass
			self.next_game_container = None
			
		if hasattr(self, 'next_game_countdown') and self.next_game_countdown:
			try:
				self.next_game_countdown.destroy()
			except:
				pass
			self.next_game_countdown = None
		
		# Increment game number
		self.current_game_number += 1
		
		# Reset all bowlers for new game
		for bowler in self.bowlers:
			bowler.frames = [Frame(balls=[], total=0) for _ in range(10)]
			bowler.current_frame = 0
			bowler.total_score = 0
			bowler.game_completed = False
		
		# Reset game state
		self.current_bowler_index = 0
		self.game_started = True
		self.hold_active = False
		
		# Update game start time for new game
		self.game_start_time = time.time()
		
		# Enable buttons
		self.ui_manager.enable_buttons(True)
		
		# Reset pins
		if 'reset_pins' in dispatcher.listeners and dispatcher.listeners['reset_pins']:
			self.reset_pins()
		
		# Update display
		if hasattr(self.parent, 'set_game_display'):
			self.parent.set_game_display(f"Current Bowler: {self.bowlers[0].name}")
		
		# Force UI re-initialization for clean start
		if hasattr(self, 'ui_manager'):
			self.ui_manager.ui_initialized = False
		
		# Update UI
		self.update_ui()
		
		logger.info(f"Started game {self.current_game_number}")
	
	def add_time(self, additional_minutes):
		if self.total_game_time_minutes is None:
			logger.warning("Cannot add time: Game is not time-based")
			return False
		
		if not self.game_started:
			logger.warning("Cannot add time: Game has not started")
			return False
		
		# Add the additional time
		old_total = self.total_game_time_minutes
		self.total_game_time_minutes += additional_minutes
		
		# Reset the time warning flag so it can show again if needed
		self.time_warning_shown = False
		
		logger.info(f"Added {additional_minutes} minutes to game. Total time: {old_total} -> {self.total_game_time_minutes} minutes")
		
		# Update time display immediately
		self._update_time_display()
		
		# Show confirmation message if possible
		if hasattr(self.parent, 'set_scroll_message'):
			dispatcher.listeners['scroll_message'][0]({f"Added {additional_minutes} minutes to your game time!"})
		
		return True

	def register_time_management_events(self):
		dispatcher.register_listener('add_time_request', self.handle_add_time_request)
		logger.info("Registered add_time_request event listener for time management")
	
	def handle_add_time_request(self, data):
		try:
			minutes_to_add = data.get('minutes', 0)
			
			if not isinstance(minutes_to_add, (int, float)) or minutes_to_add <= 0:
				response = {
					'success': False,
					'message': 'Invalid minutes value. Must be a positive number.',
					'remaining_time': self.get_remaining_time()
				}
				logger.warning(f"Add time request failed: {response['message']}")
				return response
			
			success = self.add_time(int(minutes_to_add))
			
			if success:
				response = {
					'success': True,
					'message': f'Successfully added {minutes_to_add} minutes to the game.',
					'remaining_time': self.get_remaining_time(),
					'total_time': self.total_game_time_minutes
				}
				logger.info(f"Add time request successful: {response['message']}")
				return response
			else:
				response = {
					'success': False,
					'message': 'Failed to add time. Game may not be time-based or not started.',
					'remaining_time': self.get_remaining_time()
				}
				logger.warning(f"Add time request failed: {response['message']}")
				return response
				
		except Exception as e:
			logger.error(f"Error handling add time request: {e}")
			response = {
				'success': False,
				'message': f'Error processing request: {str(e)}',
				'remaining_time': self.get_remaining_time()
			}
			return response
		
	def handle_end_game_request(self, force_end=True, reason="Server request"):
		"""Handle end game request for this specific game instance"""
		logger.info(f"Game received end game request - Force: {force_end}, Reason: {reason}")
		
		try:
			# Save current game data if not forced
			if not force_end:
				try:
					self._save_current_game_data()
					logger.info("Game data saved before forced ending")
				except Exception as e:
					logger.warning(f"Could not save game data: {e}")
			
			# Stop all timers
			self._stop_all_timers()
			
			# Update displays
			if hasattr(self.parent, 'set_game_display'):
				self.parent.set_game_display(f"Game Ended: {reason}")
			
			if hasattr(self.parent, 'set_scroll_message'):
				self.parent.set_scroll_message(f"Game ended by server: {reason}")
			
			# Call the normal end game process
			self._end_game()
			
			# Set flag to indicate this was a forced end
			self.forced_end = True
			self.end_reason = reason
			
			logger.info(f"Game ended successfully - Reason: {reason}")
			
		except Exception as e:
			logger.error(f"Error in game end game request handler: {e}")
			# Fallback: just set game_started to False
			self.game_started = False
			
	def _stop_all_timers(self):
		"""Stop all running timers in the game"""
		try:
			# Stop main timer
			if hasattr(self, 'timer_running'):
				self.timer_running = False
			
			# Stop practice timer (for league games)
			if hasattr(self, 'practice_timer_label') and self.practice_timer_label:
				self.practice_timer_label = None
			
			# Stop next game countdown
			if hasattr(self, 'next_game_countdown_seconds'):
				self.next_game_countdown_seconds = 0
			
			# Clear any after() scheduled calls
			if hasattr(self, 'frame') and self.frame:
				# Unfortunately, we can't easily cancel all after() calls
				# but setting timer_running to False should stop most loops
				pass
			
			logger.info("All game timers stopped")
			
		except Exception as e:
			logger.error(f"Error stopping timers: {e}")
	
	def get_remaining_time(self):

		if self.total_game_time_minutes is None or not self.game_started or self.game_start_time is None:
			return None
		
		elapsed_seconds = time.time() - self.game_start_time
		elapsed_minutes = elapsed_seconds / 60
		remaining_minutes = self.total_game_time_minutes - elapsed_minutes
		
		return max(0, remaining_minutes)
	
	def _should_use_machine_reading_directly(self, frame, ball_number, is_10th_frame):
		"""Comprehensive logic for when to use machine reading directly."""
		
		if ball_number == 0:  # First ball
			return True
		
		if not is_10th_frame:  # Not 10th frame
			return False
		
		# 10th frame logic
		if ball_number == 1:  # Second ball in 10th frame
			# Use machine reading if first ball was strike
			return len(frame.balls) >= 1 and frame.balls[0].value == 15
		
		elif ball_number == 2:  # Third ball in 10th frame
			# Use machine reading if:
			# - First ball was strike, OR
			# - First two balls made spare
			if len(frame.balls) >= 1 and frame.balls[0].value == 15:
				return True  # First ball strike
			elif len(frame.balls) >= 2:
				total = frame.balls[0].value + frame.balls[1].value
				return total == 15  # Spare
		
		return False
	
	def _show_next_game_button(self):
		
		logger.info("NEXT_GAME: Showing next game button")
		
		# Remove existing timer label if present
		if hasattr(self, 'timer_label') and self.timer_label:
			try:
				self.timer_label.destroy()
			except:
				pass
			self.timer_label = None
		
		# Clean up any existing next game widgets
		if hasattr(self, 'next_game_container') and self.next_game_container:
			try:
				self.next_game_container.destroy()
			except:
				pass
		
		try:
			# Create next game button and container
			self.next_game_button, self.next_game_container = self.ui_manager.create_next_game_button(
				command=self._start_next_game
			)
			
			# Create countdown label
			self.next_game_countdown = tk.Label(
				self.next_game_container,
				text="Starting in: 60",
				bg=self.settings.background_color,
				fg="red",
				font=("Arial", 16)
			)
			self.next_game_countdown.pack(side=tk.RIGHT, padx=10)
			
			# Start the countdown
			self.next_game_countdown_seconds = 60
			self._update_next_game_countdown()
			
			logger.info("NEXT_GAME: Next game button created successfully")
			
		except Exception as e:
			logger.error(f"Error creating next game button: {e}")
			
	def debug_correction_state_detailed(self):
		"""Enhanced debug method for correction state."""
		logger.info("=== DETAILED CORRECTION STATE DEBUG ===")
		
		# Current game state
		if hasattr(self, 'current_bowler_index') and self.current_bowler_index < len(self.bowlers):
			current_bowler = self.bowlers[self.current_bowler_index]
			logger.info(f"Current bowler: {current_bowler.name} (index {self.current_bowler_index})")
			logger.info(f"Current frame: {current_bowler.current_frame + 1}")
		else:
			logger.info("No valid current bowler")
		
		# Correction flags for all bowlers
		for bowler_idx, bowler in enumerate(self.bowlers):
			logger.info(f"\nBowler {bowler_idx}: {bowler.name}")
			logger.info(f"  Current frame: {bowler.current_frame + 1}")
			
			if hasattr(bowler, 'correction_flags') and bowler.correction_flags:
				for frame_idx, flag_info in bowler.correction_flags.items():
					logger.info(f"  Correction flag - Frame {frame_idx+1}: {flag_info}")
			else:
				logger.info("  No correction flags")
			
			if hasattr(bowler, 'frame_correction_active') and bowler.frame_correction_active:
				active_frames = [f+1 for f in bowler.frame_correction_active.keys()]
				logger.info(f"  Active corrections: Frames {active_frames}")
			else:
				logger.info("  No active corrections")
	
	def validate_correction_system(self):
		"""Validate the correction system is working properly."""
		validation_results = {
			"bowlers_exist": len(self.bowlers) > 0,
			"current_bowler_valid": False,
			"correction_methods_exist": True,
			"parent_exists": hasattr(self, 'parent'),
			"pin_restore_available": False
		}
		
		# Check current bowler
		if hasattr(self, 'current_bowler_index') and 0 <= self.current_bowler_index < len(self.bowlers):
			validation_results["current_bowler_valid"] = True
		
		# Check pin restore availability
		if hasattr(self, 'parent') and hasattr(self.parent, 'handle_pin_set'):
			validation_results["pin_restore_available"] = True
		
		# Check required methods
		required_methods = [
			'_save_score_corrections',
			'_handle_correction_flags_before_ball',
			'_mark_frame_for_continuation'
		]
		
		for method_name in required_methods:
			if not hasattr(self, method_name):
				validation_results["correction_methods_exist"] = False
				logger.error(f"Missing method: {method_name}")
		
		# Report results
		logger.info("=== CORRECTION SYSTEM VALIDATION ===")
		for check, result in validation_results.items():
			status = "PASS" if result else "FAIL"
			logger.info(f"{check}: {status}")
		
		return all(validation_results.values())
	
	def _save_ball_in_correction_with_flags(self, ball_idx):
		"""ENHANCED: Save ball with comprehensive frame completion and bonus handling."""
		try:
			frame = self.selected_bowler.frames[self.selected_frame]
			bowler = self.selected_bowler
			
			# Calculate what pins this ball knocked down
			ball_pins = [0, 0, 0, 0, 0]
			for i in range(5):
				if self.editing_pin_state[i] == 1 and self.initial_pin_state[i] == 0:
					ball_pins[i] = 1
			
			# Calculate ball value
			pin_values = [2, 3, 5, 3, 2]
			ball_value = sum(a * b for a, b in zip(ball_pins, pin_values))
			
			# Create symbol
			if ball_value == 15:
				symbol = 'X'
			elif ball_value == 0:
				symbol = '-'
			else:
				symbol = str(ball_value)
			
			# Create ball result
			new_ball = BallResult(
				pin_config=self.editing_pin_state.copy(),
				symbol=symbol,
				value=ball_value
			)
			
			# CRITICAL: Store original frame state before modification
			original_frame_state = self._capture_frame_state(frame, ball_idx)
			
			# Save the ball
			if ball_idx < len(frame.balls):
				frame.balls[ball_idx] = new_ball
				logger.info(f"Updated ball {ball_idx+1} in frame {self.selected_frame+1}")
			else:
				while len(frame.balls) <= ball_idx:
					if len(frame.balls) == ball_idx:
						frame.balls.append(new_ball)
					else:
						empty_ball = BallResult(pin_config=[0,0,0,0,0], symbol='-', value=0)
						frame.balls.append(empty_ball)
				logger.info(f"Added ball {ball_idx+1} to frame {self.selected_frame+1}")
			
			# Recalculate frame status
			self._recalculate_frame_status(frame)
			
			# ENHANCED: Comprehensive completion status analysis
			current_frame_state = self._capture_frame_state(frame, ball_idx)
			completion_change = self._analyze_completion_change(original_frame_state, current_frame_state)
			
			# Handle completion status changes
			if completion_change['changed']:
				self._handle_completion_change(bowler, self.selected_frame, completion_change)
			
			# CRITICAL: Recalculate ALL scores to ensure bonus consistency
			self._recalculate_all_bowler_scores()
			
			# Return to frame view
			self._select_frame_for_correction(
				self.selected_frame,
				is_last=(self.selected_frame == self._get_last_frame_with_balls()),
				is_active=(self.selected_frame == self.selected_bowler.current_frame)
			)
			
			logger.info(f"Successfully saved ball {ball_idx+1} with comprehensive completion handling")
			
		except Exception as e:
			logger.error(f"Error saving ball with flags: {str(e)}")
			tk.messagebox.showerror("Error", f"Failed to save ball: {str(e)}")
	
	def _capture_frame_state(self, frame, ball_idx):
		"""Capture comprehensive frame state before modification."""
		return {
			'ball_count': len(frame.balls),
			'is_strike': getattr(frame, 'is_strike', False),
			'is_spare': getattr(frame, 'is_spare', False),
			'was_complete': self._is_frame_complete_for_correction(frame),
			'frame_idx': self.selected_frame,
			'is_10th_frame': (self.selected_frame == 9),
			'total_value': sum(ball.value for ball in frame.balls) if frame.balls else 0,
			'ball_being_modified': ball_idx
		}
	
	def _analyze_completion_change(self, original_state, current_state):
		"""Analyze how frame completion status changed."""
		change_info = {
			'changed': False,
			'was_complete': original_state['was_complete'],
			'now_complete': current_state['was_complete'],
			'strike_change': None,  # 'added', 'removed', None
			'spare_change': None,   # 'added', 'removed', None
			'needs_continuation': False,
			'needs_pin_restoration': False,
			'affects_current_play': False
		}
		
		# Check strike status changes
		if original_state['is_strike'] != current_state['is_strike']:
			change_info['strike_change'] = 'added' if current_state['is_strike'] else 'removed'
			change_info['changed'] = True
		
		# Check spare status changes
		if original_state['is_spare'] != current_state['is_spare']:
			change_info['spare_change'] = 'added' if current_state['is_spare'] else 'removed'
			change_info['changed'] = True
		
		# Check completion status changes
		if original_state['was_complete'] != current_state['was_complete']:
			change_info['changed'] = True
			
			# Frame was complete but now isn't - needs continuation
			if original_state['was_complete'] and not current_state['was_complete']:
				change_info['needs_continuation'] = True
		
		# Check if this affects current active play
		current_bowler = self.bowlers[self.current_bowler_index]
		if (current_bowler == self.selected_bowler and 
			self.selected_frame == current_bowler.current_frame):
			change_info['affects_current_play'] = True
			
			# If we now have a strike or spare, and this is the current frame, we need pin restoration
			if (current_state['is_strike'] or current_state['is_spare']) and change_info['affects_current_play']:
				change_info['needs_pin_restoration'] = True
		
		logger.info(f"CORRECTION_ANALYSIS: {change_info}")
		return change_info
	
	def _handle_completion_change(self, bowler, frame_idx, change_info):
		"""Handle frame completion status changes with appropriate actions."""
		
		if change_info['needs_continuation']:
			# Frame was complete but now isn't - mark for continuation
			self._mark_frame_for_continuation(bowler, frame_idx)
			logger.info(f"CORRECTION_CONTINUATION: Frame {frame_idx+1} marked for continuation")
		
		# Handle strike/spare additions that complete the frame
		if change_info['strike_change'] == 'added' or change_info['spare_change'] == 'added':
			if not change_info['affects_current_play']:
				logger.info(f"CORRECTION_COMPLETE: Strike/spare added to completed frame {frame_idx+1}")
			else:
				logger.info(f"CORRECTION_CURRENT: Strike/spare added to current frame {frame_idx+1}")
				# This will be handled in the pin restoration logic
		
		# Handle strike/spare removals
		if change_info['strike_change'] == 'removed' or change_info['spare_change'] == 'removed':
			logger.info(f"CORRECTION_REMOVAL: Strike/spare removed from frame {frame_idx+1}")
			# Bonus recalculation is handled in _recalculate_all_bowler_scores
	
	def _is_frame_complete_for_correction(self, frame):
		"""Determine if frame is complete for correction purposes."""
		try:
			is_10th_frame = (self.selected_frame == 9)
			
			if not is_10th_frame:
				# Regular frames (1-9)
				if len(frame.balls) >= 3:
					return True  # Three balls = complete
				elif len(frame.balls) >= 1 and frame.balls[0].value == 15:
					return True  # Strike = complete
				elif len(frame.balls) >= 2:
					total = frame.balls[0].value + frame.balls[1].value
					return total == 15  # Spare = complete
			else:
				# 10th frame - requires 3 balls unless open after 2
				if len(frame.balls) >= 3:
					return True
				elif len(frame.balls) == 2:
					first_ball = frame.balls[0].value
					second_ball = frame.balls[1].value
					# Complete if no strike/spare in first two balls
					return first_ball < 15 and (first_ball + second_ball) < 15
			
			return False
			
		except Exception as e:
			logger.error(f"Error determining frame completion: {e}")
			return False
	
	def _recalculate_all_bowler_scores(self):
		"""Recalculate scores for all bowlers to ensure bonus consistency."""
		logger.info("CORRECTION_RECALC: Recalculating all bowler scores for bonus consistency")
		
		for bowler in self.bowlers:
			# Reset all frame calculations
			for frame in bowler.frames:
				if hasattr(frame, 'bonus_balls'):
					frame.bonus_balls = []
				if hasattr(frame, 'base_score'):
					frame.base_score = 0
				if hasattr(frame, 'bonus_score'):
					frame.bonus_score = 0
			
			# Recalculate from scratch
			self._calculate_all_scores(bowler)
		
		logger.info("CORRECTION_RECALC: All bowler scores recalculated")
	
	def _save_score_corrections(self):
		"""ENHANCED: Save corrections with comprehensive pin restoration logic."""
		try:
			logger.info("Starting comprehensive score correction save")
			
			# ENHANCED: Track correction context with completion analysis
			correction_context = self._analyze_comprehensive_correction_context()
			
			# Recalculate ALL scores for ALL bowlers
			self._recalculate_all_bowler_scores()
			
			# Force complete UI rebuild
			logger.info("Forcing complete UI rebuild")
			self._rebuild_ui_completely()
			
			# Close the correction window
			self._close_score_correction()
			
			# ENHANCED: Show success with comprehensive pin restoration options
			self._show_enhanced_correction_success(correction_context)
			
			logger.info("Score corrections saved and UI updated successfully")
			
		except Exception as e:
			logger.error(f"Error saving score corrections: {str(e)}")
			error_msg = f"Failed to save score corrections:\n{str(e)}\n\nPlease try again or contact support."
			tk.messagebox.showerror("Save Error", error_msg)
	
	def _analyze_comprehensive_correction_context(self):
		"""ENHANCED: Comprehensive correction context analysis with pin state tracking."""
		try:
			context = {
				'current_bowler_affected': False,
				'current_frame_affected': False,
				'affected_bowler_name': None,
				'affected_frame_idx': None,
				'current_bowler_idx': getattr(self, 'current_bowler_index', None),
				'selected_bowler_name': getattr(self.selected_bowler, 'name', None) if hasattr(self, 'selected_bowler') else None,
				'selected_frame_idx': getattr(self, 'selected_frame', None),
				'completion_changed': False,
				'strike_or_spare_added': False,
				'frame_now_complete': False,
				'has_continuation_flag': False,
				'frame_needs_completion': False,
				'should_offer_options': False,
				'corrected_balls_count': 0,
				'frame_was_incomplete': False
			}
			
			# Always set affected bowler info
			if hasattr(self, 'selected_bowler') and hasattr(self, 'selected_frame'):
				context['affected_bowler_name'] = self.selected_bowler.name
				context['affected_frame_idx'] = self.selected_frame
				
				# Get corrected frame details
				corrected_frame = self.selected_bowler.frames[self.selected_frame]
				context['corrected_balls_count'] = len(corrected_frame.balls)
				
				# Check if frame was originally incomplete (needed continuation)
				if hasattr(self.selected_bowler, 'correction_flags'):
					if self.selected_frame in self.selected_bowler.correction_flags:
						flag_info = self.selected_bowler.correction_flags[self.selected_frame]
						if flag_info.get('needs_continuation', False):
							context['has_continuation_flag'] = True
							context['frame_was_incomplete'] = True
				
				# Check if the corrected frame is now complete with strike/spare
				if hasattr(corrected_frame, 'is_strike') and corrected_frame.is_strike:
					context['strike_or_spare_added'] = True
					context['frame_now_complete'] = True
				elif hasattr(corrected_frame, 'is_spare') and corrected_frame.is_spare:
					context['strike_or_spare_added'] = True  
					context['frame_now_complete'] = True
			
			# Check if we're correcting the current bowler's current frame
			if (hasattr(self, 'current_bowler_index') and 
				hasattr(self, 'selected_bowler') and
				self.current_bowler_index < len(self.bowlers)):
				
				current_bowler = self.bowlers[self.current_bowler_index]
				
				if current_bowler == self.selected_bowler:
					context['current_bowler_affected'] = True
					
					if (hasattr(self, 'selected_frame') and 
						self.selected_frame == current_bowler.current_frame):
						context['current_frame_affected'] = True
			
			context['should_offer_options'] = (
				(context['current_bowler_affected'] and context['current_frame_affected']) or
				context['has_continuation_flag'] or
				(context['strike_or_spare_added'] and context['frame_now_complete'])
			)
			
			# Special logic for frames needing completion
			if context['has_continuation_flag'] or (context['strike_or_spare_added'] and context['frame_now_complete']):
				context['frame_needs_completion'] = True
			
			logger.info(f"ENHANCED_CORRECTION_CONTEXT: {context}")
			return context
			
		except Exception as e:
			logger.error(f"Error analyzing correction context: {e}")
			return {'current_bowler_affected': False, 'current_frame_affected': False, 'should_offer_options': False}
		
	def _show_enhanced_correction_success(self, context):
		"""ENHANCED: Show success message with intelligent pin restoration options."""
		try:
			# Check if we should offer any options at all
			if not context.get('should_offer_options', False):
				# Simple success message and return
				self._show_simple_correction_success(context)
				return
			
			# Create success popup for complex scenarios
			success_popup = tk.Toplevel(self.frame)
			success_popup.title("Score Correction Saved")
			success_popup.geometry("650x450")
			success_popup.configure(bg="darkgreen")
			success_popup.attributes("-topmost", True)
			success_popup.grab_set()
			
			# Center the popup
			success_popup.transient(self.frame)
			success_popup.update_idletasks()
			width = success_popup.winfo_width()
			height = success_popup.winfo_height()
			x = (success_popup.winfo_screenwidth() // 2) - (width // 2)
			y = (success_popup.winfo_screenheight() // 2) - (height // 2)
			success_popup.geometry(f'{width}x{height}+{x}+{y}')
			
			# Main container
			main_frame = tk.Frame(success_popup, bg="darkgreen")
			main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
			
			# Success message
			tk.Label(
				main_frame,
				text="✓ SCORE CORRECTIONS SAVED!",
				bg="darkgreen",
				fg="white",
				font=("Arial", 18, "bold")
			).pack(pady=(0, 10))
			
			tk.Label(
				main_frame,
				text="All scores and bonuses have been recalculated",
				bg="darkgreen",
				fg="white",
				font=("Arial", 12)
			).pack(pady=(0, 20))
			
			# Show correction details
			if context.get('affected_bowler_name'):
				tk.Label(
					main_frame,
					text=f"Corrected: {context['affected_bowler_name']}, Frame {context.get('affected_frame_idx', 0) + 1}",
					bg="darkgreen",
					fg="yellow",
					font=("Arial", 12, "bold")
				).pack(pady=(0, 10))
			
			# ENHANCED: Different scenarios based on context
			current_bowler_affected = context.get('current_bowler_affected', False)
			current_frame_affected = context.get('current_frame_affected', False)
			strike_or_spare_added = context.get('strike_or_spare_added', False)
			frame_now_complete = context.get('frame_now_complete', False)
			has_continuation_flag = context.get('has_continuation_flag', False)
			frame_needs_completion = context.get('frame_needs_completion', False)
			
			logger.info(f"PIN_RESTORE_ANALYSIS: bowler_affected={current_bowler_affected}, "
					   f"frame_affected={current_frame_affected}, strike_spare_added={strike_or_spare_added}, "
					   f"frame_complete={frame_now_complete}, continuation_flag={has_continuation_flag}")
			
			# SCENARIO 1: Current bowler's current frame corrected to strike/spare
			if current_bowler_affected and current_frame_affected and strike_or_spare_added and frame_now_complete:
				tk.Label(
					main_frame,
					text="CORRECTION COMPLETED CURRENT FRAME!",
					bg="darkgreen",
					fg="orange",
					font=("Arial", 14, "bold")
				).pack(pady=(0, 5))
				
				tk.Label(
					main_frame,
					text="The current player's frame now has a strike or spare.",
					bg="darkgreen",
					fg="white",
					font=("Arial", 11)
				).pack(pady=(0, 10))
				
				tk.Label(
					main_frame,
					text="Do you want to finish this frame and advance to the next bowler?",
					bg="darkgreen",
					fg="white",
					font=("Arial", 11, "bold")
				).pack(pady=(0, 15))
				
				# Finish frame button
				finish_frame_btn = tk.Button(
					main_frame,
					text="FINISH FRAME & ADVANCE",
					command=lambda: self._finish_corrected_frame_and_advance(success_popup, context),
					font=("Arial", 12, "bold"),
					bg="orange",
					fg="white",
					height=2
				)
				finish_frame_btn.pack(fill=tk.X, pady=5)
				
				# Continue frame button
				continue_frame_btn = tk.Button(
					main_frame,
					text="CONTINUE CURRENT FRAME",
					command=lambda: self._continue_corrected_frame(success_popup, context),
					font=("Arial", 10),
					bg="blue",
					fg="white",
					height=1
				)
				continue_frame_btn.pack(fill=tk.X, pady=2)
			
			# SCENARIO 2: Any frame corrected to strike/spare (not current bowler)
			elif strike_or_spare_added and frame_now_complete and not (current_bowler_affected and current_frame_affected):
				tk.Label(
					main_frame,
					text="FRAME CORRECTED TO STRIKE/SPARE!",
					bg="darkgreen",
					fg="orange",
					font=("Arial", 14, "bold")
				).pack(pady=(0, 5))
				
				tk.Label(
					main_frame,
					text=f"{context['affected_bowler_name']}'s frame {context.get('affected_frame_idx', 0) + 1} now has a strike or spare.",
					bg="darkgreen",
					fg="white",
					font=("Arial", 11)
				).pack(pady=(0, 10))
				
				tk.Label(
					main_frame,
					text="Do you want to switch to that bowler to continue/finish their frame?",
					bg="darkgreen",
					fg="white",
					font=("Arial", 11, "bold")
				).pack(pady=(0, 15))
				
				# Switch to bowler button
				switch_bowler_btn = tk.Button(
					main_frame,
					text=f"SWITCH TO {context['affected_bowler_name'].upper()}",
					command=lambda: self._switch_to_corrected_bowler(success_popup, context),
					font=("Arial", 12, "bold"),
					bg="orange",
					fg="white",
					height=2
				)
				switch_bowler_btn.pack(fill=tk.X, pady=5)
				
				# Stay with current bowler button
				stay_current_btn = tk.Button(
					main_frame,
					text="STAY WITH CURRENT BOWLER",
					command=success_popup.destroy,
					font=("Arial", 10),
					bg="blue",
					fg="white",
					height=1
				)
				stay_current_btn.pack(fill=tk.X, pady=2)
			
			# SCENARIO 3: Frame has continuation flag (was complete, now incomplete)
			elif has_continuation_flag:
				tk.Label(
					main_frame,
					text="FRAME NEEDS CONTINUATION!",
					bg="darkgreen",
					fg="yellow",
					font=("Arial", 14, "bold")
				).pack(pady=(0, 5))
				
				tk.Label(
					main_frame,
					text=f"{context['affected_bowler_name']}'s frame {context.get('affected_frame_idx', 0) + 1} was completed but now needs more balls.",
					bg="darkgreen",
					fg="white",
					font=("Arial", 11)
				).pack(pady=(0, 10))
				
				tk.Label(
					main_frame,
					text="Do you want to switch to that bowler to continue their frame?",
					bg="darkgreen",
					fg="white",
					font=("Arial", 11, "bold")
				).pack(pady=(0, 15))
				
				# Switch to continue button
				continue_bowler_btn = tk.Button(
					main_frame,
					text=f"SWITCH TO {context['affected_bowler_name'].upper()} & CONTINUE",
					command=lambda: self._switch_to_continue_frame(success_popup, context),
					font=("Arial", 12, "bold"),
					bg="yellow",
					fg="black",
					height=2
				)
				continue_bowler_btn.pack(fill=tk.X, pady=5)
				
				# Stay with current bowler button
				stay_current_btn = tk.Button(
					main_frame,
					text="STAY WITH CURRENT BOWLER",
					command=success_popup.destroy,
					font=("Arial", 10),
					bg="blue",
					fg="white",
					height=1
				)
				stay_current_btn.pack(fill=tk.X, pady=2)
			
			# SCENARIO 4: Current bowler's current frame modified (normal case)
			elif current_bowler_affected and current_frame_affected:
				tk.Label(
					main_frame,
					text="CURRENT FRAME MODIFIED!",
					bg="darkgreen",
					fg="yellow",
					font=("Arial", 14, "bold")
				).pack(pady=(0, 5))
				
				tk.Label(
					main_frame,
					text="The current bowler's active frame was modified.",
					bg="darkgreen",
					fg="white",
					font=("Arial", 11)
				).pack(pady=(0, 10))
				
				tk.Label(
					main_frame,
					text="Would you like to set the pins to match the corrected state?",
					bg="darkgreen",
					fg="white",
					font=("Arial", 11, "bold")
				).pack(pady=(0, 15))
				
				# Pin restoration button
				pin_restore_btn = tk.Button(
					main_frame,
					text="SET PINS TO MATCH CORRECTION",
					command=lambda: self._restore_pins_after_correction_enhanced(success_popup, context),
					font=("Arial", 12, "bold"),
					bg="orange",
					fg="white",
					height=2
				)
				pin_restore_btn.pack(fill=tk.X, pady=5)
			
			# Close button (always present)
			close_btn = tk.Button(
				main_frame,
				text="CLOSE",
				command=success_popup.destroy,
				font=("Arial", 12, "bold"),
				bg="white",
				fg="darkgreen",
				height=2
			)
			close_btn.pack(fill=tk.X, pady=(10, 0))
			
			# Auto-close after 30 seconds if no critical action needed
			if not frame_needs_completion:
				success_popup.after(30000, success_popup.destroy)
			
		except Exception as e:
			logger.error(f"Error showing enhanced correction success: {e}")
	
	def _show_simple_correction_success(self, context):
		"""Show simple success message for non-critical corrections."""
		try:
			success_popup = tk.Toplevel(self.frame)
			success_popup.title("Score Correction Saved")
			success_popup.geometry("400x200")
			success_popup.configure(bg="darkgreen")
			success_popup.attributes("-topmost", True)
			
			# Center the popup
			success_popup.transient(self.frame)
			success_popup.update_idletasks()
			width = success_popup.winfo_width()
			height = success_popup.winfo_height()
			x = (success_popup.winfo_screenwidth() // 2) - (width // 2)
			y = (success_popup.winfo_screenheight() // 2) - (height // 2)
			success_popup.geometry(f'{width}x{height}+{x}+{y}')
			
			main_frame = tk.Frame(success_popup, bg="darkgreen")
			main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
			
			tk.Label(
				main_frame,
				text="✓ SCORE CORRECTIONS SAVED!",
				bg="darkgreen",
				fg="white",
				font=("Arial", 16, "bold")
			).pack(pady=10)
			
			tk.Label(
				main_frame,
				text="Scores and bonuses have been updated.",
				bg="darkgreen",
				fg="white",
				font=("Arial", 12)
			).pack(pady=10)
			
			if context.get('affected_bowler_name'):
				tk.Label(
					main_frame,
					text=f"Corrected: {context['affected_bowler_name']}, Frame {context.get('affected_frame_idx', 0) + 1}",
					bg="darkgreen",
					fg="yellow",
					font=("Arial", 10)
				).pack(pady=5)
			
			tk.Button(
				main_frame,
				text="OK",
				command=success_popup.destroy,
				font=("Arial", 12, "bold"),
				bg="white",
				fg="darkgreen"
			).pack(pady=10)
			
			# Auto-close after 5 seconds
			success_popup.after(5000, success_popup.destroy)
			
		except Exception as e:
			logger.error(f"Error showing simple correction success: {e}")
	
	def _switch_to_corrected_bowler(self, popup, context):
		"""Switch to the bowler whose frame was corrected with FIXED context."""
		try:
			popup.destroy()
			
			# Find the corrected bowler and switch to them
			affected_bowler_name = context.get('affected_bowler_name')
			affected_frame_idx = context.get('affected_frame_idx')
			
			corrected_bowler_idx = None
			for idx, bowler in enumerate(self.bowlers):
				if bowler.name == affected_bowler_name:
					corrected_bowler_idx = idx
					self.current_bowler_index = idx
					bowler.current_frame = affected_frame_idx
					
					logger.info(f"CORRECTION_SWITCH: Switched to {affected_bowler_name}, frame {affected_frame_idx + 1}")
					break
			
			if corrected_bowler_idx is None:
				logger.error(f"Could not find bowler {affected_bowler_name}")
				return
			
			# Update UI
			self.update_ui()
			
			# Update displays
			if hasattr(self.parent, 'set_game_display'):
				self.parent.set_game_display(f"Current Bowler: {affected_bowler_name}")
			
			# CRITICAL FIX: Create updated context with correct bowler index
			updated_context = context.copy()
			updated_context['current_bowler_idx'] = corrected_bowler_idx  # Use the corrected bowler's index
			updated_context['current_bowler_affected'] = True  # Now it affects current bowler
			updated_context['current_frame_affected'] = True   # And current frame
			
			logger.info(f"CONTEXT_FIX: Updated context - current_bowler_idx changed from {context.get('current_bowler_idx')} to {corrected_bowler_idx}")
			
			# Show confirmation with pin restoration option using UPDATED context
			self._show_switch_confirmation_with_pins(updated_context)
			
		except Exception as e:
			logger.error(f"Error switching to corrected bowler: {e}")
	
	def _switch_to_continue_frame(self, popup, context):
		"""Switch to bowler who needs to continue their frame with FIXED context."""
		try:
			popup.destroy()
			
			# Find the bowler and switch to them
			affected_bowler_name = context.get('affected_bowler_name')
			affected_frame_idx = context.get('affected_frame_idx')
			
			corrected_bowler_idx = None
			for idx, bowler in enumerate(self.bowlers):
				if bowler.name == affected_bowler_name:
					corrected_bowler_idx = idx
					self.current_bowler_index = idx
					bowler.current_frame = affected_frame_idx
					
					logger.info(f"CORRECTION_CONTINUE: Switched to {affected_bowler_name} to continue frame {affected_frame_idx + 1}")
					break
			
			if corrected_bowler_idx is None:
				logger.error(f"Could not find bowler {affected_bowler_name}")
				return
			
			# Update UI
			self.update_ui()
			
			# Update displays
			if hasattr(self.parent, 'set_game_display'):
				self.parent.set_game_display(f"Current Bowler: {affected_bowler_name}")
			
			# CRITICAL FIX: Create updated context with correct bowler index
			updated_context = context.copy()
			updated_context['current_bowler_idx'] = corrected_bowler_idx  # Use the corrected bowler's index
			updated_context['current_bowler_affected'] = True  # Now it affects current bowler
			updated_context['current_frame_affected'] = True   # And current frame
			
			logger.info(f"CONTEXT_FIX: Updated context - current_bowler_idx changed from {context.get('current_bowler_idx')} to {corrected_bowler_idx}")
			
			# Show confirmation with pin restoration using UPDATED context
			self._show_continue_confirmation_with_pins(updated_context)
			
		except Exception as e:
			logger.error(f"Error switching to continue frame: {e}")
			
	def _show_continue_confirmation_with_pins(self, context):
		"""Show confirmation after switching to continue frame with FIXED context pin restoration."""
		try:
			confirm_popup = tk.Toplevel(self.frame)
			confirm_popup.title("Continuing Frame")
			confirm_popup.geometry("500x250")
			confirm_popup.configure(bg="orange")
			confirm_popup.attributes("-topmost", True)
			
			# Center the popup
			confirm_popup.transient(self.frame)
			confirm_popup.update_idletasks()
			width = confirm_popup.winfo_width()
			height = confirm_popup.winfo_height()
			x = (confirm_popup.winfo_screenwidth() // 2) - (width // 2)
			y = (confirm_popup.winfo_screenheight() // 2) - (height // 2)
			confirm_popup.geometry(f'{width}x{height}+{x}+{y}')
			
			main_frame = tk.Frame(confirm_popup, bg="orange")
			main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
			
			tk.Label(
				main_frame,
				text=f"✓ CONTINUING {context['affected_bowler_name'].upper()}'S FRAME",
				bg="orange",
				fg="black",
				font=("Arial", 16, "bold")
			).pack(pady=10)
			
			tk.Label(
				main_frame,
				text=f"Frame {context.get('affected_frame_idx', 0) + 1} was corrected and needs more balls",
				bg="orange",
				fg="black",
				font=("Arial", 12)
			).pack(pady=5)
			
			tk.Label(
				main_frame,
				text="Set pins to match the current corrected state?",
				bg="orange",
				fg="black",
				font=("Arial", 11, "bold")
			).pack(pady=10)
			
			# Pin restoration button with CORRECTED context
			pin_restore_btn = tk.Button(
				main_frame,
				text="SET PINS TO MATCH",
				command=lambda: self._restore_pins_after_correction_enhanced(confirm_popup, context),
				font=("Arial", 12, "bold"),
				bg="darkgreen",
				fg="white"
			)
			pin_restore_btn.pack(pady=5)
			
			# Close button
			tk.Button(
				main_frame,
				text="CONTINUE WITHOUT PIN SET",
				command=confirm_popup.destroy,
				font=("Arial", 10),
				bg="white",
				fg="orange"
			).pack(pady=5)
			
			# Auto-close after 10 seconds
			confirm_popup.after(10000, confirm_popup.destroy)
			
		except Exception as e:
			logger.error(f"Error showing continue confirmation: {e}")
			
	def _show_switch_confirmation_with_pins(self, context):
		"""Show confirmation after switching with FIXED context pin restoration option."""
		try:
			confirm_popup = tk.Toplevel(self.frame)
			confirm_popup.title("Switched Bowler")
			confirm_popup.geometry("500x250")
			confirm_popup.configure(bg="blue")
			confirm_popup.attributes("-topmost", True)
			
			# Center the popup
			confirm_popup.transient(self.frame)
			confirm_popup.update_idletasks()
			width = confirm_popup.winfo_width()
			height = confirm_popup.winfo_height()
			x = (confirm_popup.winfo_screenwidth() // 2) - (width // 2)
			y = (confirm_popup.winfo_screenheight() // 2) - (height // 2)
			confirm_popup.geometry(f'{width}x{height}+{x}+{y}')
			
			main_frame = tk.Frame(confirm_popup, bg="blue")
			main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
			
			tk.Label(
				main_frame,
				text=f"✓ SWITCHED TO {context['affected_bowler_name'].upper()}",
				bg="blue",
				fg="white",
				font=("Arial", 16, "bold")
			).pack(pady=10)
			
			tk.Label(
				main_frame,
				text=f"Now on Frame {context.get('affected_frame_idx', 0) + 1} with corrected state",
				bg="blue",
				fg="white",
				font=("Arial", 12)
			).pack(pady=5)
			
			tk.Label(
				main_frame,
				text="Set pins to match the corrected state?",
				bg="blue",
				fg="white",
				font=("Arial", 11, "bold")
			).pack(pady=10)
			
			# Pin restoration button with CORRECTED context
			pin_restore_btn = tk.Button(
				main_frame,
				text="SET PINS TO MATCH",
				command=lambda: self._restore_pins_after_correction_enhanced(confirm_popup, context),
				font=("Arial", 12, "bold"),
				bg="orange",
				fg="white"
			)
			pin_restore_btn.pack(pady=5)
			
			# Close button
			tk.Button(
				main_frame,
				text="CONTINUE WITHOUT PIN SET",
				command=confirm_popup.destroy,
				font=("Arial", 10),
				bg="white",
				fg="blue"
			).pack(pady=5)
			
			# Auto-close after 10 seconds
			confirm_popup.after(10000, confirm_popup.destroy)
			
		except Exception as e:
			logger.error(f"Error showing switch confirmation: {e}")
	
	def _show_enhanced_correction_success_part2(self, context, success_popup, main_frame, 
											  current_bowler_affected, current_frame_affected,
											  strike_or_spare_added, frame_now_complete):
		"""Second part of the enhanced correction success logic."""
		try:
			if current_bowler_affected and current_frame_affected:
				if strike_or_spare_added and frame_now_complete:
					# Special case: correction resulted in strike/spare completing the frame
					tk.Label(
						main_frame,
						text="CORRECTION COMPLETED FRAME!",
						bg="darkgreen",
						fg="orange",
						font=("Arial", 14, "bold")
					).pack(pady=(0, 5))
					
					tk.Label(
						main_frame,
						text="The correction resulted in a strike or spare, completing the frame.",
						bg="darkgreen",
						fg="white",
						font=("Arial", 11)
					).pack(pady=(0, 10))
					
					tk.Label(
						main_frame,
						text="Do you want to finish this frame and advance to the next bowler?",
						bg="darkgreen",
						fg="white",
						font=("Arial", 11, "bold")
					).pack(pady=(0, 15))
					
					# Finish frame button
					finish_frame_btn = tk.Button(
						main_frame,
						text="FINISH FRAME & ADVANCE",
						command=lambda: self._finish_corrected_frame_and_advance(success_popup, context),
						font=("Arial", 12, "bold"),
						bg="orange",
						fg="white",
						height=2
					)
					finish_frame_btn.pack(fill=tk.X, pady=5)
					
					# Continue frame button
					continue_frame_btn = tk.Button(
						main_frame,
						text="CONTINUE CURRENT FRAME",
						command=lambda: self._continue_corrected_frame(success_popup, context),
						font=("Arial", 10),
						bg="blue",
						fg="white",
						height=1
					)
					continue_frame_btn.pack(fill=tk.X, pady=2)
					
				else:
					# Normal case: set pins to match corrected state
					tk.Label(
						main_frame,
						text="The current bowler's active frame was modified.",
						bg="darkgreen",
						fg="yellow",
						font=("Arial", 12, "bold")
					).pack(pady=(0, 10))
					
					tk.Label(
						main_frame,
						text="Would you like to set the pins to match the corrected state?",
						bg="darkgreen",
						fg="white",
						font=("Arial", 11)
					).pack(pady=(0, 15))
					
					# Pin restoration button
					pin_restore_btn = tk.Button(
						main_frame,
						text="SET PINS TO MATCH CORRECTION",
						command=lambda: self._restore_pins_after_correction_enhanced(success_popup, context),
						font=("Arial", 12, "bold"),
						bg="orange",
						fg="white",
						height=2
					)
					pin_restore_btn.pack(fill=tk.X, pady=5)
			else:
				# Not affecting current play
				logger.info("PIN_RESTORE_SKIP: Not affecting current bowler's current frame")
				
				if context.get('affected_bowler_name'):
					current_bowler_name = self.bowlers[self.current_bowler_index].name if hasattr(self, 'current_bowler_index') and self.current_bowler_index < len(self.bowlers) else "Unknown"
					
					if not current_bowler_affected:
						reason_text = f"Corrected {context['affected_bowler_name']}, but current bowler is {current_bowler_name}"
					else:
						reason_text = "Corrected a completed frame, not the active frame"
					
					tk.Label(
						main_frame,
						text=reason_text,
						bg="darkgreen",
						fg="lightgray",
						font=("Arial", 10)
					).pack(pady=(0, 10))
			
			# Close button
			close_btn = tk.Button(
				main_frame,
				text="CLOSE",
				command=success_popup.destroy,
				font=("Arial", 12, "bold"),
				bg="white",
				fg="darkgreen",
				height=2
			)
			close_btn.pack(fill=tk.X, pady=(10, 0))
			
			# Auto-close after 20 seconds if no action needed
			if not (current_bowler_affected and current_frame_affected):
				success_popup.after(20000, success_popup.destroy)
			
		except Exception as e:
			logger.error(f"Error showing enhanced correction success: {e}")
	
	def _finish_corrected_frame_and_advance(self, popup, context):
		"""Finish the corrected frame and advance to next bowler with FIXED context."""
		try:
			popup.destroy()
			
			# CRITICAL FIX: Use the affected bowler, not current bowler from context
			affected_bowler_name = context.get('affected_bowler_name')
			affected_frame_idx = context.get('affected_frame_idx')
			
			# Find the corrected bowler
			target_bowler = None
			target_bowler_idx = None
			for idx, bowler in enumerate(self.bowlers):
				if bowler.name == affected_bowler_name:
					target_bowler = bowler
					target_bowler_idx = idx
					break
			
			if target_bowler is None:
				logger.error(f"Could not find bowler {affected_bowler_name} for frame completion")
				return
			
			# Switch to that bowler and frame
			self.current_bowler_index = target_bowler_idx
			target_bowler.current_frame = affected_frame_idx
			
			logger.info(f"CORRECTION_FINISH: Finishing corrected frame {affected_frame_idx + 1} for {target_bowler.name}")
			
			# Advance the frame/bowler as if the frame was naturally completed
			if affected_frame_idx < 9:  # Not 10th frame
				self._advance_frame(target_bowler)
			else:  # 10th frame
				self._end_bowler_game(target_bowler)
			
			# Reset pins for next bowler/frame
			self._schedule_immediate_full_reset('correction_frame_finish')
			
			# Update UI
			self.update_ui()
			
			# Show confirmation
			if hasattr(self.parent, 'set_scroll_message'):
				self.parent.set_scroll_message("Frame completed by correction - advanced to next")
			
			logger.info("CORRECTION_FINISH: Frame completed and advanced successfully")
			
		except Exception as e:
			logger.error(f"Error finishing corrected frame: {e}")
			tk.messagebox.showerror("Error", f"Failed to finish frame: {str(e)}")
	
	def _continue_corrected_frame(self, popup, context):
		"""Continue with the corrected frame with FIXED context."""
		try:
			popup.destroy()
			
			# CRITICAL FIX: Create updated context with correct bowler information
			affected_bowler_name = context.get('affected_bowler_name')
			
			# Find the corrected bowler index
			corrected_bowler_idx = None
			for idx, bowler in enumerate(self.bowlers):
				if bowler.name == affected_bowler_name:
					corrected_bowler_idx = idx
					break
			
			if corrected_bowler_idx is None:
				logger.error(f"Could not find bowler {affected_bowler_name}")
				return
			
			# Create updated context
			updated_context = context.copy()
			updated_context['current_bowler_idx'] = corrected_bowler_idx
			
			logger.info(f"CORRECTION_CONTINUE: Using corrected bowler index {corrected_bowler_idx} for pin restoration")
			
			# Restore pins to match the corrected state using FIXED context
			self._restore_pins_after_correction_enhanced(None, updated_context)
			
		except Exception as e:
			logger.error(f"Error continuing corrected frame: {e}")
			
	def _show_frame_complete_message(self, frame_type):
		"""Show message that frame is complete and no pin restoration is needed."""
		try:
			message_popup = tk.Toplevel(self.frame)
			message_popup.title("Frame Complete")
			message_popup.geometry("400x200")
			message_popup.configure(bg="green")
			message_popup.attributes("-topmost", True)
			
			# Center the popup
			message_popup.transient(self.frame)
			message_popup.update_idletasks()
			width = message_popup.winfo_width()
			height = message_popup.winfo_height()
			x = (message_popup.winfo_screenwidth() // 2) - (width // 2)
			y = (message_popup.winfo_screenheight() // 2) - (height // 2)
			message_popup.geometry(f'{width}x{height}+{x}+{y}')
			
			main_frame = tk.Frame(message_popup, bg="green")
			main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
			
			tk.Label(
				main_frame,
				text=f"✓ {frame_type.upper()} FRAME COMPLETE",
				bg="green",
				fg="white",
				font=("Arial", 16, "bold")
			).pack(pady=10)
			
			tk.Label(
				main_frame,
				text=f"This frame has a {frame_type.lower()} and is complete.\nNo pin restoration needed.",
				bg="green",
				fg="white",
				font=("Arial", 12),
				justify=tk.CENTER
			).pack(pady=10)
			
			tk.Button(
				main_frame,
				text="OK",
				command=message_popup.destroy,
				font=("Arial", 12, "bold"),
				bg="white",
				fg="green"
			).pack(pady=10)
			
			# Auto-close after 5 seconds
			message_popup.after(5000, message_popup.destroy)
			
		except Exception as e:
			logger.error(f"Error showing frame complete message: {e}")

	
	def _show_enhanced_pin_restore_confirmation_with_details(self, pin_state, balls_thrown, pins_reset):
		"""Show enhanced confirmation with details about pin state."""
		try:
			confirmation_popup = tk.Toplevel(self.frame)
			confirmation_popup.title("Pins Restored")
			confirmation_popup.geometry("600x350")
			confirmation_popup.configure(bg="blue")
			confirmation_popup.attributes("-topmost", True)
			
			# Center the popup
			confirmation_popup.transient(self.frame)
			confirmation_popup.update_idletasks()
			width = confirmation_popup.winfo_width()
			height = confirmation_popup.winfo_height()
			x = (confirmation_popup.winfo_screenwidth() // 2) - (width // 2)
			y = (confirmation_popup.winfo_screenheight() // 2) - (height // 2)
			confirmation_popup.geometry(f'{width}x{height}+{x}+{y}')
			
			main_frame = tk.Frame(confirmation_popup, bg="blue")
			main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
			
			tk.Label(
				main_frame,
				text="✓ PINS SET TO MATCH\nCORRECTED STATE",
				bg="blue",
				fg="white",
				font=("Arial", 16, "bold"),
				justify=tk.CENTER
			).pack(expand=True, pady=10)
			
			# Show different messages based on pin reset status
			if pins_reset:
				tk.Label(
					main_frame,
					text="Pins were RESET after strike/spare",
					bg="blue",
					fg="yellow",
					font=("Arial", 14, "bold")
				).pack(pady=5)
				
				tk.Label(
					main_frame,
					text="All pins are now UP for the next ball",
					bg="blue",
					fg="white",
					font=("Arial", 12)
				).pack(pady=5)
			else:
				# Show pin state details
				pin_names = ["Left 2", "Left 3", "Center 5", "Right 3", "Right 2"]
				pin_states = []
				for i, (name, state) in enumerate(zip(pin_names, pin_state)):
					state_text = "DOWN" if state == 1 else "UP"
					pin_states.append(f"{name}: {state_text}")
				
				tk.Label(
					main_frame,
					text=f"After {balls_thrown} corrected balls:",
					bg="blue",
					fg="white",
					font=("Arial", 12, "bold")
				).pack(pady=5)
				
				tk.Label(
					main_frame,
					text="\n".join(pin_states),
					bg="blue",
					fg="white",
					font=("Arial", 11),
					justify=tk.CENTER
				).pack(expand=True, pady=10)
			
			tk.Label(
				main_frame,
				text="The physical pins now match the corrected state.\nYou can continue playing from this position.",
				bg="blue",
				fg="white",
				font=("Arial", 12),
				justify=tk.CENTER
			).pack(expand=True, pady=10)
			
			# Manual close button
			tk.Button(
				main_frame,
				text="OK",
				command=confirmation_popup.destroy,
				font=("Arial", 12, "bold"),
				bg="white",
				fg="blue"
			).pack(pady=10)
			
			# Auto-close after 8 seconds
			confirmation_popup.after(8000, confirmation_popup.destroy)
			
		except Exception as e:
			logger.error(f"Error showing enhanced pin restore confirmation: {e}")
	
	def _rebuild_ui_completely(self):
		"""Completely rebuild the UI to reflect all changes."""
		try:
			# Clear the current UI completely
			for widget in self.frame.winfo_children():
				widget.destroy()
			
			# Recreate UI manager with updated data
			self.ui_manager = GameUIManager(self.frame, self.bowlers, self.settings, self)
			self.ui_manager.set_button_callbacks(
				on_reset=self.reset_pins,
				on_skip=self.skip_bowler,
				on_hold=self.toggle_hold,
				on_settings=self.open_settings,
				on_pin_restore=self.pin_restore
			)
			
			# Force complete UI re-render
			self.ui_manager.ui_initialized = False
			self.update_ui()
			
			logger.info("UI completely rebuilt after score corrections")
			
		except Exception as e:
			logger.error(f"Error rebuilding UI: {e}")
			# Fallback to basic update
			self.update_ui()
			
	def handle_pin_set_direct(self, pin_data):

		logger.info(f"Direct pin set requested with data: {pin_data}")
		
		if hasattr(self.parent, 'machine'):
			# Use new pin_set function instead of pin_restore
			self.parent.machine.pin_set(pin_data)
			logger.info("Direct pin set command sent to machine")
		else:
			logger.error("No machine available for direct pin set")
	
	def _perform_revert_last_ball(self, target_bowler_idx, target_frame_idx, target_ball_idx, target_bowler, target_frame):
		"""FIXED: Perform revert with proper frame status recalculation"""
		logger.info(f"Enhanced revert: ball {target_ball_idx + 1} from {target_bowler.name}, frame {target_frame_idx + 1}")
		
		# Store original states for restoration
		original_bowler_idx = self.current_bowler_index
		
		# Calculate correct pin state after removing this ball
		pins_should_be = self._calculate_pin_state_after_revert(target_frame, target_ball_idx)
		
		# Remove the ball
		removed_ball = target_frame.balls.pop(target_ball_idx)
		logger.info(f"Removed ball: {removed_ball.symbol} (value: {removed_ball.value})")
		
		# CRITICAL: Recalculate frame status PROPERLY after ball removal
		self._recalculate_frame_status_after_revert_fixed(target_frame)
		
		# Determine correct game state after revert
		correct_state = self._determine_correct_game_state_after_revert(
			target_bowler_idx, target_frame_idx, target_ball_idx, target_bowler, target_frame
		)
		
		# Apply the correct game state
		self.current_bowler_index = correct_state['bowler_index']
		target_bowler.current_frame = correct_state['current_frame']
		
		# Recalculate all scores
		for bowler in self.bowlers:
			self._calculate_all_scores(bowler)
		
		# Handle machine state
		if hasattr(self.parent, 'machine'):
			if correct_state['needs_full_reset']:
				self.parent.machine._force_full_reset = True
				logger.info("REVERT: Set full reset flag")
			else:
				# Restore pins to calculated state
				logger.info(f"REVERT: Restoring pins to state: {pins_should_be}")
				if 'pin_set' in dispatcher.listeners and dispatcher.listeners['pin_set']:
					dispatcher.listeners['pin_set'][0](pins_should_be)
		
		# Update UI
		self.update_ui()
		
		# Update game display
		if hasattr(self, 'parent') and hasattr(self.parent, 'set_game_display'):
			current_bowler = self.bowlers[self.current_bowler_index]
			self.parent.set_game_display(f"Current Bowler: {current_bowler.name}")
		
		logger.info(f"Enhanced revert complete. Game state: Bowler {self.bowlers[self.current_bowler_index].name}, Frame {self.bowlers[self.current_bowler_index].current_frame + 1}")
	
	
	def _recalculate_frame_status_after_revert_fixed(self, frame):
		"""FIXED: Recalculate frame status after ball removal with proper spare detection"""
		frame.is_strike = False
		frame.is_spare = False
		
		if not frame.balls:
			return
		
		# Check for strike (first ball = 15) - ONLY on first ball
		if len(frame.balls) >= 1 and frame.balls[0].value == 15:
			frame.is_strike = True
			logger.info("REVERT: Frame recalculated as STRIKE")
			return  # Strike cannot also be spare
		
		# Check for spare (first two balls = 15, but NOT a strike)
		if len(frame.balls) >= 2:
			first_ball_value = frame.balls[0].value
			second_ball_value = frame.balls[1].value
			total_first_two = first_ball_value + second_ball_value
			
			if total_first_two == 15 and first_ball_value < 15:
				frame.is_spare = True
				logger.info(f"REVERT: Frame recalculated as SPARE ({first_ball_value} + {second_ball_value} = 15)")
			else:
				logger.info(f"REVERT: Open frame ({first_ball_value} + {second_ball_value} = {total_first_two})")
		
		logger.info(f"REVERT: Final frame status - Strike={frame.is_strike}, Spare={frame.is_spare}")


	def _restore_pins_after_correction_enhanced(self, popup, context):

		try:
			if popup:
				popup.destroy()
			
			# ... existing context validation code stays the same ...
			
			# Get current bowler and frame using context
			current_bowler_idx = context.get('current_bowler_idx')
			affected_frame_idx = context.get('affected_frame_idx')
			affected_bowler_name = context.get('affected_bowler_name')
			
			# CRITICAL FIX: Validate and correct bowler index if needed
			if affected_bowler_name:
				verified_bowler_idx = None
				for idx, bowler in enumerate(self.bowlers):
					if bowler.name == affected_bowler_name:
						verified_bowler_idx = idx
						break
				
				if verified_bowler_idx is not None:
					if current_bowler_idx != verified_bowler_idx:
						logger.info(f"CONTEXT_CORRECTION: Bowler index mismatch - context says {current_bowler_idx}, but {affected_bowler_name} is at index {verified_bowler_idx}")
						current_bowler_idx = verified_bowler_idx
				else:
					logger.error(f"PIN_RESTORE_ERROR: Could not find bowler {affected_bowler_name}")
					return
			
			if current_bowler_idx is None or affected_frame_idx is None:
				logger.error("PIN_RESTORE_ERROR: Missing context information after correction")
				tk.messagebox.showerror("Pin Restore Error", "Cannot determine which frame to restore pins for")
				return
			
			current_bowler = self.bowlers[current_bowler_idx]
			current_frame = current_bowler.frames[affected_frame_idx]
			is_10th_frame = (affected_frame_idx == 9)
			
			logger.info(f"PIN_RESTORE_ENHANCED: Restoring pins for {current_bowler.name} (index {current_bowler_idx}), Frame {affected_frame_idx + 1}")
			
			# ... existing pin state calculation logic stays the same ...
			
			# Calculate pin state based on CORRECTED ball states
			pin_state = [0, 0, 0, 0, 0]
			balls_thrown = len(current_frame.balls)
			logger.info(f"PIN_RESTORE_ENHANCED: Frame has {balls_thrown} balls thrown")
			
			# Log the actual balls for verification
			for ball_idx, ball in enumerate(current_frame.balls):
				logger.info(f"PIN_RESTORE_ENHANCED: Ball {ball_idx+1}: pin_config={ball.pin_config}, value={ball.value}, symbol={ball.symbol}")
			
			# CANADIAN 5-PIN LOGIC: Check if pins should be reset for continuation
			pins_should_be_reset = False
			
			if is_10th_frame:
				if balls_thrown >= 1 and current_frame.balls[0].value == 15:
					pins_should_be_reset = True
					logger.info("PIN_RESTORE_10TH: Strike - pins reset for next ball")
				elif balls_thrown >= 2:
					first_two_total = current_frame.balls[0].value + current_frame.balls[1].value
					if first_two_total == 15:
						pins_should_be_reset = True
						logger.info("PIN_RESTORE_10TH: Spare - pins reset for third ball")
			else:
				# Regular frames: check if frame should be complete
				if balls_thrown >= 1 and current_frame.balls[0].value == 15:
					logger.info("PIN_RESTORE_REGULAR: Strike frame complete - no pin restoration needed")
					self._show_frame_complete_message("Strike")
					return
				elif balls_thrown >= 2:
					first_two_total = current_frame.balls[0].value + current_frame.balls[1].value
					if first_two_total == 15:
						logger.info("PIN_RESTORE_REGULAR: Spare frame complete - no pin restoration needed")
						self._show_frame_complete_message("Spare")
						return
			
			# Calculate pin state
			if pins_should_be_reset:
				pin_state = [0, 0, 0, 0, 0]
				logger.info("PIN_RESTORE_ENHANCED: Pins reset state - all pins up")
			else:
				for ball_idx, ball in enumerate(current_frame.balls):
					logger.info(f"PIN_RESTORE_ENHANCED: Applying ball {ball_idx+1}: {ball.pin_config} (value: {ball.value})")
					for pin_idx, pin_knocked in enumerate(ball.pin_config):
						if pin_knocked == 1:
							pin_state[pin_idx] = 1  # Pin is down
			
			logger.info(f"PIN_RESTORE_ENHANCED: Final calculated pin state: {pin_state}")
			
			# Convert to machine control format (1 = up, 0 = down)
			machine_control = {
				'lTwo': 0 if pin_state[0] == 1 else 1,
				'lThree': 0 if pin_state[1] == 1 else 1,
				'cFive': 0 if pin_state[2] == 1 else 1,
				'rThree': 0 if pin_state[3] == 1 else 1,
				'rTwo': 0 if pin_state[4] == 1 else 1
			}
			
			logger.info(f"PIN_RESTORE_ENHANCED: Setting machine control via DIRECT pin_set: {machine_control}")
			
			# CRITICAL: Use direct pin setting for corrections (bypasses timing restrictions)
			success = False
			
			# Method 1: Direct pin set via parent (NEW METHOD)
			if hasattr(self, 'handle_pin_set_direct'):
				try:
					self.handle_pin_set_direct(machine_control)
					success = True
					logger.info("PIN_RESTORE_ENHANCED: Success via direct handle_pin_set_direct")
				except Exception as e:
					logger.warning(f"PIN_RESTORE_ENHANCED: handle_pin_set_direct failed: {e}")
			
			# Method 2: Direct machine access (NEW METHOD)
			if not success and hasattr(self.parent, 'machine') and hasattr(self.parent.machine, 'pin_set'):
				try:
					self.parent.machine.pin_set(machine_control)
					success = True
					logger.info("PIN_RESTORE_ENHANCED: Success via direct machine.pin_set")
				except Exception as e:
					logger.warning(f"PIN_RESTORE_ENHANCED: direct machine.pin_set failed: {e}")
			
			# Method 3: Fallback to regular pin_restore (EXISTING METHOD)
			if not success and hasattr(self.parent, 'handle_pin_set'):
				try:
					self.parent.handle_pin_set(machine_control)
					success = True
					logger.info("PIN_RESTORE_ENHANCED: Fallback success via regular handle_pin_set")
				except Exception as e:
					logger.warning(f"PIN_RESTORE_ENHANCED: fallback failed: {e}")
			
			if success:
				self._show_enhanced_pin_restore_confirmation_with_details(pin_state, balls_thrown, pins_should_be_reset)
			else:
				logger.error("PIN_RESTORE_ENHANCED: All pin restoration methods failed")
				tk.messagebox.showerror("Pin Restore Error", "Failed to restore pins using all available methods")
			
			logger.info("Enhanced pin restoration after correction completed")
			
		except Exception as e:
			logger.error(f"Error in enhanced pin restoration: {e}")
			tk.messagebox.showerror("Pin Restore Error", f"Failed to restore pins: {str(e)}")
	
	def update_ui(self):
		"""OPTIMIZED: Update the UI to show the current game state."""
		ui_start_time = time.time()
		
		# PERFORMANCE: Early exit conditions
		if not self.game_started:
			logger.info("UI_UPDATE_SKIP: Game not started, skipping update")
			return
		
		# PERFORMANCE: Debounce rapid updates
		if hasattr(self, '_last_ui_update') and time.time() - self._last_ui_update < 0.1:
			logger.info("UI_UPDATE_DEBOUNCE: Skipping update due to debouncing")
			return
		
		self._last_ui_update = time.time()
		
		logger.info(f"UI_UPDATE_START: Starting UI update at {ui_start_time:.3f}")
		
		# PERFORMANCE: Validate current_bowler_index once
		if self.current_bowler_index >= len(self.bowlers):
			logger.warning(f"Invalid current_bowler_index {self.current_bowler_index}, resetting to 0")
			self.current_bowler_index = 0
		
		# PERFORMANCE: Update UI manager bowler references once
		if hasattr(self, 'ui_manager'):
			self.ui_manager.bowlers = self.bowlers
		
		# PERFORMANCE: Single render call with all required data
		render_start = time.time()
		logger.info(f"UI_RENDER: Rendering with current_bowler_index = {self.current_bowler_index}")
		self.ui_manager.render(self.current_bowler_index, self.hold_active)
		logger.info(f"UI_RENDER_COMPLETE: UI rendered in {time.time() - render_start:.3f}s")
		
		# PERFORMANCE: Batch display updates
		if hasattr(self, 'parent') and hasattr(self.parent, 'set_game_display'):
			display_start = time.time()
			current_bowler = self.bowlers[self.current_bowler_index]
			logger.info(f"UI_DISPLAY_UPDATE: Setting game display for bowler: {current_bowler.name}")
			self.parent.set_game_display(f"Current Bowler: {current_bowler.name}")
			logger.info(f"UI_DISPLAY_COMPLETE: Display updated in {time.time() - display_start:.3f}s")
		
		# PERFORMANCE: Only update time display if it's a time-based game
		if hasattr(self, 'parent') and hasattr(self, 'total_game_time_minutes') and self.total_game_time_minutes:
			self._update_time_display()
		
		logger.info(f"UI_UPDATE_COMPLETE: UI update completed in {time.time() - ui_start_time:.3f}s")


class LeagueGame(QuickGame):

	def __init__(self, bowlers: List[Dict], settings: GameSettings, paired_lane=None, parent=None):
		# Extract bowler names for parent constructor
		bowler_names = [b["name"] for b in bowlers]
		super().__init__(bowlers=bowler_names, settings=settings, parent=parent)
		
		# Override the bowlers list with league-specific data
		self.bowlers = []
		for b in bowlers:
			frames = [Frame(balls=[], total=0) for _ in range(10)]
			bowler = Bowler(
				name=b["name"], 
				handicap=b.get("handicap", 0), 
				frames=frames,
				absent=b.get("absent", False),
				default_score=b.get("default_score", 0)
			)
			
			# Add league-specific attributes
			bowler.average = b.get("average", getattr(settings, 'default_avg', 150))  # Use default_avg from settings
			bowler.poa = 0  # Pins Over Average - calculated dynamically
			
			# Handle absent bowlers with default scores
			if bowler.absent and bowler.default_score > 0:
				for frame in frames:
					ball = BallResult(
						pin_config=[0, 0, 0, 0, 0],
						symbol=str(bowler.default_score),
						value=bowler.default_score
					)
					frame.balls.append(ball)
					frame.total = bowler.default_score
				bowler.current_frame = 10
				bowler.total_score = bowler.default_score * 10
				
			self.bowlers.append(bowler)
		
		# League-specific settings
		self.paired_lane = paired_lane
		self.lane_id = lane_settings["Lane"]
		self.max_bowlers_on_screen = 8
		self.current_game_number = 1
		
		# Properly extract total_display setting
		self.total_display_mode = getattr(settings, 'total_display', 'regular')
		logger.info(f"LeagueGame total_display_mode set to: {self.total_display_mode}")
		
		# Practice mode setup using getattr
		self.practice_mode = not getattr(settings, 'skip_practice', False)
		self.practice_end_time = None
		self.practice_timer_label = None
		
		# Team movement tracking
		self.frames_per_turn = settings.frames_per_turn
		self.wait_for_pair = getattr(settings, 'wait_for_pair', False)  # use getattr
		self.pair_ready = False
		self.team_data_cache = {}  # Cache team data during movement
		
		# UI optimization flags
		self.ui_needs_rebuild = True
		self.last_bowler_count = len(self.bowlers)
		
		# Register league-specific events
		self._register_league_events()
		self._showing_waiting_ui = False
		
		# Override UI manager with league-specific version
		self.ui_manager = LeagueUIManager(self.frame, self.bowlers, self.settings, self)
		self.ui_manager.set_button_callbacks(
			on_reset=self.reset_pins,
			on_skip=self.skip_bowler,
			on_hold=self.toggle_hold,
			on_settings=self.open_settings,
			on_pin_restore=self.pin_restore
		)
		
		logger.info(f"LeagueGame initialized: Lane {self.lane_id}, paired with {paired_lane}, "
				f"{len(bowlers)} bowlers, total_display='{self.total_display_mode}'")
		
	def _register_league_events(self):
		"""Register league-specific event listeners"""
		dispatcher.register_listener('bowler_move', self.handle_bowler_move)
		dispatcher.register_listener('team_move', self.handle_team_move)
		dispatcher.register_listener('frame_update', self.handle_frame_update)
		dispatcher.register_listener('game_complete', self.handle_game_complete)
		dispatcher.register_listener('pair_ready', self.handle_pair_ready)
		logger.info("League event listeners registered")
	
	def start(self):
		"""Start the league game with practice mode handling"""
		logger.info(f"Starting LeagueGame on lane {self.lane_id}")
		
		# Skip practice mode for testing if configured
		if hasattr(self.settings, 'skip_practice') and self.settings.skip_practice:
			logger.info("Skipping practice mode")
			self.practice_mode = False
			self.game_started = True
			
			if self.wait_for_pair and not self.pair_ready:
				self._show_waiting_for_pair_ui()
				self._notify_paired_lane_ready()
				return
			
			self.update_ui()
			return
		
		# Normal practice mode flow
		if self.practice_mode:
			self.practice_end_time = time.time() + 1800  # 30 minutes
			self._show_practice_mode_ui()
			self._update_practice_timer()
		else:
			self.game_started = True
			self.update_ui()

	def reset_pins(self):
		"""Manual reset via button - do immediate reset"""
		# Allow reset during practice mode OR when game has started
		if not self.game_started and not self.practice_mode:
			logger.info("Cannot reset pins: Game has not started and not in practice mode.")
			return
	
		logger.info("Manual reset_pins requested - executing immediately")
		
		# Enhanced debugging for reset button
		logger.info(f"RESET_DEBUG: Game started: {self.game_started}")
		logger.info(f"RESET_DEBUG: Practice mode: {getattr(self, 'practice_mode', 'Not set')}")
		logger.info(f"RESET_DEBUG: Hold active: {getattr(self, 'hold_active', 'Not set')}")
		logger.info(f"RESET_DEBUG: Parent exists: {hasattr(self, 'parent')}")
		logger.info(f"RESET_DEBUG: Parent machine exists: {hasattr(self.parent, 'machine') if hasattr(self, 'parent') else 'No parent'}")
		
		# For manual reset button, do immediate reset via machine
		if hasattr(self.parent, 'machine'):
			logger.info("MANUAL_RESET: Calling machine reset_pins directly")
			self.parent.machine.reset_pins()
		else:
			logger.error("No machine available for manual reset")
	
	def _show_practice_mode_ui(self):
		"""Display practice mode interface"""
		for widget in self.frame.winfo_children():
			widget.destroy()
		
		practice_container = tk.Frame(self.frame, bg=self.settings.background_color)
		practice_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
		
		# Practice header
		tk.Label(
			practice_container,
			text="PRACTICE MODE",
			bg=self.settings.background_color,
			fg="yellow",
			font=("Arial", 36, "bold")
		).pack(pady=20)
		
		# Timer
		self.practice_timer_label = tk.Label(
			practice_container,
			text="Time Remaining: 30:00",
			bg=self.settings.background_color,
			fg="white",
			font=("Arial", 24)
		)
		self.practice_timer_label.pack(pady=10)
		
		# Instructions
		tk.Label(
			practice_container,
			text="League bowling will begin when practice time ends",
			bg=self.settings.background_color,
			fg=self.settings.foreground_color,
			font=("Arial", 16)
		).pack(pady=20)
		
		# Control buttons
		button_frame = tk.Frame(practice_container, bg=self.settings.background_color)
		button_frame.pack(pady=20)
		
		tk.Button(
			button_frame,
			text="RESET PINS",
			bg="green",
			fg="white",
			command=self.reset_pins,
			font=("Arial", 20)
		).pack(side=tk.LEFT, padx=10)
		
		tk.Button(
			button_frame,
			text="END PRACTICE",
			bg="red",
			fg="white",
			command=self._end_practice_mode,
			font=("Arial", 20)
		).pack(side=tk.LEFT, padx=10)
		
		# Activate ball detector for practice
		if hasattr(self.parent, 'activate_ball_detector'):
			self.parent.activate_ball_detector()
	
	def _update_practice_timer(self):
		"""Update practice timer countdown"""
		if not self.practice_mode:
			return
		
		if time.time() >= self.practice_end_time:
			self._end_practice_mode()
			return
		
		remaining = int(self.practice_end_time - time.time())
		minutes = remaining // 60
		seconds = remaining % 60
		
		if self.practice_timer_label:
			self.practice_timer_label.config(text=f"Time Remaining: {minutes:02d}:{seconds:02d}")
		
		self.frame.after(1000, self._update_practice_timer)
	

	def _end_practice_mode(self):
		"""End practice mode and start league game"""
		self.practice_mode = False
		self.game_started = True
		self.ui_needs_rebuild = True
		
		logger.info("Practice mode ended, starting league game")
		logger.info("Ball detector continues running from practice mode")
		
		if hasattr(self.parent, 'set_game_display'):
			self.parent.set_game_display("League Game Started")
		
		self.update_ui()
	
	def _show_waiting_for_pair_ui(self):
		"""Show waiting for paired lane interface"""
		for widget in self.frame.winfo_children():
			widget.destroy()
		
		waiting_container = tk.Frame(self.frame, bg=self.settings.background_color)
		waiting_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
		
		tk.Label(
			waiting_container,
			text=f"WAITING FOR LANE {self.paired_lane}",
			bg=self.settings.background_color,
			fg="yellow",
			font=("Arial", 36, "bold")
		).pack(pady=20)
		
		tk.Label(
			waiting_container,
			text="League bowling will begin when both lanes are ready",
			bg=self.settings.background_color,
			fg=self.settings.foreground_color,
			font=("Arial", 16)
		).pack(pady=20)
	
	def _advance_frame(self, bowler: Bowler):
		"""Override frame advancement to handle team movement"""
		if bowler.current_frame < 9:
			bowler.current_frame += 1
			logger.info(f"Advanced {bowler.name} to frame {bowler.current_frame + 1}")
		else:
			logger.info(f"Bowler {bowler.name} completed all frames")
			self._end_bowler_game(bowler)
			return
		
		# Check if ALL bowlers have completed their frames_per_turn, not just current bowler
		if self.paired_lane and self._check_team_movement_needed():
			logger.info(f"All bowlers completed {self.frames_per_turn} frames, preparing for lane movement")
			self._prepare_team_movement()
		else:
			# Check if current bowler should continue or move to next bowler
			frames_completed_this_turn = (bowler.current_frame % self.frames_per_turn)
			
			if frames_completed_this_turn == 0:  # Current bowler completed their turn
				logger.info(f"{bowler.name} completed {self.frames_per_turn} frames, moving to next bowler")
				self._move_to_next_bowler()
			else:
				logger.info(f"{bowler.name} continues with frame {bowler.current_frame + 1}")
		
		# Reset button back to normal
		if hasattr(self.ui_manager, 'set_reset_button_to_normal'):
			self.ui_manager.set_reset_button_to_normal()
	
	def _check_team_movement_needed(self):
		"""Check if all bowlers have completed their frames_per_turn and team should move"""
		if not self.paired_lane:
			return False
		
		# Check if all bowlers have completed at least frames_per_turn frames
		min_frames_needed = self.frames_per_turn
		
		for bowler in self.bowlers:
			# Count completed frames (frames with balls)
			completed_frames = sum(1 for frame in bowler.frames if frame.balls)
			
			# Check if this bowler has completed enough frames for movement
			if completed_frames < min_frames_needed:
				logger.info(f"Bowler {bowler.name} has only completed {completed_frames} frames, need {min_frames_needed}")
				return False
		
		logger.info(f"All bowlers have completed at least {min_frames_needed} frames - team movement needed")
		return True
	
	def _prepare_team_movement(self):
		"""Prepare current team data for movement to paired lane"""
		logger.info("Preparing team movement to paired lane")
		
		# IMPORTANT: Temporarily suspend ball detector during team movement
		if hasattr(self.parent, 'ball_detector') and self.parent.ball_detector:
			if hasattr(self.parent.ball_detector, 'set_suspended'):
				self.parent.ball_detector.set_suspended(True)
				logger.info("Ball detector suspended during team movement")
		
		# Cache current team data
		team_data = {
			"bowlers": [],
			"from_lane": self.lane_id,
			"to_lane": self.paired_lane,
			"game_number": self.current_game_number,
			"timestamp": time.time()
		}
		
		for bowler in self.bowlers:
			bowler_data = {
				"name": bowler.name,
				"handicap": bowler.handicap,
				"average": getattr(bowler, 'average', 0),
				"frames": [
					{
						"balls": [
							{
								"pin_config": ball.pin_config,
								"symbol": ball.symbol,
								"value": ball.value
							} for ball in frame.balls
						],
						"total": frame.total,
						"is_strike": frame.is_strike,
						"is_spare": frame.is_spare
					} for frame in bowler.frames
				],
				"current_frame": bowler.current_frame,
				"total_score": bowler.total_score,
				"absent": getattr(bowler, 'absent', False),
				"default_score": getattr(bowler, 'default_score', 0)
			}
			team_data["bowlers"].append(bowler_data)
		
		# Send team data to paired lane
		self._send_team_to_paired_lane(team_data)
		
		# Clear current bowlers and show waiting UI
		self.bowlers = []
		self.ui_needs_rebuild = True
		self._show_waiting_for_team_ui()
	
	def _send_team_to_paired_lane(self, team_data):
		"""Send team data to paired lane"""
		try:
			if hasattr(self.parent, 'send_to_lane'):
				message = {
					"type": "team_move",
					"data": team_data
				}
				success = self.parent.send_to_lane(self.paired_lane, 'team_move', message)
				if success:
					logger.info(f"Team data sent to lane {self.paired_lane}")
				else:
					logger.error(f"Failed to send team data to lane {self.paired_lane}")
			else:
				logger.error("No send_to_lane method available")
		except Exception as e:
			logger.error(f"Error sending team data: {e}")
	
	def _show_waiting_for_team_ui(self):
		"""Show waiting for team return interface with safe widget handling"""
		self._safe_clear_widgets()
		
		waiting_container = tk.Frame(self.frame, bg=self.settings.background_color)
		waiting_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
		
		tk.Label(
			waiting_container,
			text="WAITING FOR TEAM",
			bg=self.settings.background_color,
			fg="yellow",
			font=("Arial", 36, "bold")
		).pack(pady=20)
		
		if self.paired_lane:
			tk.Label(
				waiting_container,
				text=f"Team is currently bowling on Lane {self.paired_lane}",
				bg=self.settings.background_color,
				fg=self.settings.foreground_color,
				font=("Arial", 16)
			).pack(pady=10)
		
		tk.Label(
			waiting_container,
			text="Game will resume when team returns",
			bg=self.settings.background_color,
			fg=self.settings.foreground_color,
			font=("Arial", 14)
		).pack(pady=10)
		
		# Reset button for manual control
		tk.Button(
			waiting_container,
			text="RESET PINS",
			bg="green",
			fg="white",
			command=self.reset_pins,
			font=("Arial", 20)
		).pack(pady=20)
	
	def handle_team_move(self, data):
		"""FIXED: Handle team move with proper ball detector preservation"""
		logger.info(f"🚀 HANDLE_TEAM_MOVE: Receiving team from lane {data.get('from_lane')}")
		
		# CRITICAL: Store ball detector state BEFORE any changes
		detector_state = None
		if hasattr(self.parent, 'ball_detector') and self.parent.ball_detector:
			detector_state = {
				'instance': self.parent.ball_detector,
				'threshold': getattr(self.parent.ball_detector, 'detection_threshold', 10),
				'debounce': getattr(self.parent.ball_detector, 'debounce_time', 0.5),
				'running': getattr(self.parent.ball_detector, 'running', True)
			}
			# DON'T suspend - just update references
			logger.info("Ball detector state preserved")
		
		# Process the team move
		if hasattr(self, 'frame') and self.frame:
			self.frame.after_idle(lambda: self._process_team_move_fixed(data, detector_state))
		else:
			self._process_team_move_fixed(data, detector_state)
	
	def _process_team_move_fixed(self, data, detector_state):
		"""Process team move with ball detector fix"""
		try:
			logger.info("Processing team move with ball detector fix")
			
			# Clear and rebuild game state
			self.bowlers = []
			self._safe_clear_widgets()
			self._reconstruct_bowlers_from_data(data)
			
			# Reset game state
			self.current_bowler_index = 0
			self.ui_needs_rebuild = True
			
			# Force UI manager reinitialization
			if hasattr(self, 'ui_manager'):
				self.ui_manager.ui_initialized = False
			
			# Update UI
			self.update_ui()
			
			# CRITICAL FIX: Restore ball detector with proper game reference
			if detector_state and detector_state['instance']:
				detector = detector_state['instance']
				
				# Update game reference to THIS game instance
				detector.game = self
				logger.info("✅ Ball detector game reference updated")
				
				# Ensure machine context is correct
				if hasattr(self.parent, 'machine'):
					detector.machine = self.parent.machine
					self.parent.machine.game_context = self
					logger.info("✅ Machine context updated")
				
				# Ensure detector is NOT suspended
				if hasattr(detector, 'suspended'):
					detector.suspended = False
				
				# Verify the detector is still running
				if hasattr(detector, 'running') and not detector.running:
					detector.running = True
					logger.info("✅ Ball detector reactivated")
				
				logger.info("✅ Ball detector successfully restored after team move")
			else:
				# No detector existed, create new one
				logger.info("Creating new ball detector after team move")
				if hasattr(self.parent, 'setup_ball_detector'):
					self.parent.setup_ball_detector()
			
			# Update displays
			if hasattr(self.parent, 'set_game_display') and self.bowlers:
				current_bowler = self.bowlers[self.current_bowler_index]
				self.parent.set_game_display(f"League: {current_bowler.name}")
			
			logger.info(f"✅ Team move complete with working ball detection")
			return True
			
		except Exception as e:
			logger.error(f"Error in team move: {e}")
			# Emergency fallback - ensure detector exists
			if hasattr(self.parent, 'ball_detector') and self.parent.ball_detector:
				self.parent.ball_detector.game = self
				self.parent.ball_detector.suspended = False
			return False
	
	
	def _preserve_ball_detector_state(self):
		"""Preserve ball detector state before team movement"""
		try:
			if not hasattr(self.parent, 'ball_detector') or not self.parent.ball_detector:
				logger.info("ℹ️ No ball detector to preserve")
				return None
			
			detector = self.parent.ball_detector
			
			# Preserve key state information
			preserved_state = {
				'detector_instance': detector,  # Keep the actual instance
				'machine_ref': getattr(detector, 'machine', None),
				'suspended_state': getattr(detector, 'suspended', False),
				'detection_active': False,
				'thread_alive': False
			}
			
			# Check if detection is active
			if hasattr(detector, 'detection_thread'):
				preserved_state['thread_alive'] = detector.detection_thread and detector.detection_thread.is_alive()
			
			if hasattr(detector, 'is_detecting'):
				if callable(detector.is_detecting):
					preserved_state['detection_active'] = detector.is_detecting()
			
			logger.info(f"🔒 PRESERVED: Ball detector state - Active: {preserved_state['detection_active']}, Thread: {preserved_state['thread_alive']}")
			return preserved_state
			
		except Exception as e:
			logger.error(f"❌ Error preserving ball detector state: {e}")
			return None
	
	def handle_team_move_with_thread_fix(self, data):
		"""Handle team move with thread fix"""
		logger.info(f"🚀 HANDLE_TEAM_MOVE: Receiving team from lane {data.get('from_lane')}")
		
		if hasattr(self, 'frame') and self.frame:
			self.frame.after_idle(lambda: self._process_team_move_with_thread_fix(data))
		else:
			self._process_team_move_with_thread_fix(data)
	
	def _restore_ball_detector_state_with_thread_fix(self, preserved_state):
		"""FIXED: Restore ball detector state with proper thread restart"""
		try:
			logger.info("🔓 RESTORE_ENHANCED: Restoring ball detector state with thread fix")
			
			detector = preserved_state['detector_instance']
			
			# Step 1: Update game reference to new game instance
			detector.game = self
			logger.info("🔓 Updated detector game reference")
			
			# Step 2: Ensure machine context is updated
			if hasattr(self.parent, 'machine'):
				self.parent.machine.game_context = self
				if preserved_state['machine_ref']:
					detector.machine = self.parent.machine
				logger.info("🔓 Updated machine references")
			
			# Step 3: CRITICAL - Check if detector has detection capabilities
			has_detection_thread = hasattr(detector, 'detection_thread')
			has_is_detecting = hasattr(detector, 'is_detecting')
			has_start_detection = hasattr(detector, 'start_detection')
			
			logger.info(f"🔍 DETECTOR_CAPABILITIES: thread={has_detection_thread}, is_detecting={has_is_detecting}, start_detection={has_start_detection}")
			
			# Step 4: If detector lacks detection capabilities, enhance it
			if not has_detection_thread or not has_is_detecting:
				logger.info("🔧 ENHANCING: Detector lacks detection capabilities, enhancing...")
				self._enhance_detector_with_detection(detector)
			
			# Step 5: Restore detection state
			if hasattr(detector, 'set_suspended'):
				detector.set_suspended(False)
				logger.info("🔓 Detector unsuspended")
			
			# Step 6: Start or restart detection
			detection_started = False
			
			# Method 1: Use start_detection if available
			if hasattr(detector, 'start_detection'):
				try:
					detector.start_detection()
					detection_started = True
					logger.info("🔓 Detection started via start_detection()")
				except Exception as e:
					logger.warning(f"start_detection failed: {e}")
			
			# Method 2: Use resume_detection if available
			if not detection_started and hasattr(detector, 'resume_detection'):
				try:
					detector.resume_detection()
					detection_started = True
					logger.info("🔓 Detection resumed via resume_detection()")
				except Exception as e:
					logger.warning(f"resume_detection failed: {e}")
			
			# Method 3: Direct thread restart if available
			if not detection_started and hasattr(detector, '_start_detection_thread'):
				try:
					detector._start_detection_thread()
					detection_started = True
					logger.info("🔓 Detection thread started directly")
				except Exception as e:
					logger.warning(f"Direct thread start failed: {e}")
			
			# Method 4: Force recreation of detection thread
			if not detection_started:
				logger.info("🔧 FORCE_RESTART: Creating new detection thread")
				self._force_restart_detection_thread(detector)
				detection_started = True
			
			# Step 7: Verify the detector is working
			time.sleep(1.0)  # Give it a moment to initialize
			
			verification_passed = self._verify_detection_working(detector)
			
			if verification_passed:
				logger.info("✅ RESTORE_SUCCESS: Ball detector fully restored and detecting")
				return True
			else:
				logger.error("❌ RESTORE_PARTIAL: Detector restored but not detecting properly")
				# Try emergency restart
				return self._emergency_detection_restart(detector)
			
		except Exception as e:
			logger.error(f"❌ Error restoring ball detector state: {e}")
			return False

	
	
	def _verify_ball_detector_functionality(self):
		"""Verify ball detector is functioning after team movement"""
		try:
			logger.info("🧪 VERIFY: Testing ball detector functionality")
			
			if not hasattr(self.parent, 'ball_detector') or not self.parent.ball_detector:
				logger.error("❌ VERIFY_FAIL: No ball detector found")
				return False
			
			detector = self.parent.ball_detector
			
			# Test 1: Check basic properties
			tests_passed = 0
			total_tests = 5
			
			# Test 1: Game reference
			if hasattr(detector, 'game') and detector.game == self:
				tests_passed += 1
				logger.info("✅ TEST 1: Game reference correct")
			else:
				logger.error("❌ TEST 1: Game reference incorrect")
			
			# Test 2: Machine reference
			if hasattr(detector, 'machine') and detector.machine:
				tests_passed += 1
				logger.info("✅ TEST 2: Machine reference exists")
			else:
				logger.error("❌ TEST 2: Machine reference missing")
			
			# Test 3: Not suspended
			if hasattr(detector, 'suspended'):
				if not detector.suspended:
					tests_passed += 1
					logger.info("✅ TEST 3: Detector not suspended")
				else:
					logger.error("❌ TEST 3: Detector is suspended")
			else:
				tests_passed += 1  # Assume good if no suspension property
				logger.info("✅ TEST 3: No suspension property (assumed good)")
			
			# Test 4: Thread status
			if hasattr(detector, 'detection_thread'):
				if detector.detection_thread and detector.detection_thread.is_alive():
					tests_passed += 1
					logger.info("✅ TEST 4: Detection thread alive")
				else:
					logger.error("❌ TEST 4: Detection thread not alive")
			else:
				logger.warning("⚠️ TEST 4: No detection thread property")
			
			# Test 5: Detection status
			if hasattr(detector, 'is_detecting'):
				if callable(detector.is_detecting):
					if detector.is_detecting():
						tests_passed += 1
						logger.info("✅ TEST 5: Detector is detecting")
					else:
						logger.error("❌ TEST 5: Detector not detecting")
				else:
					logger.warning("⚠️ TEST 5: is_detecting not callable")
			else:
				logger.warning("⚠️ TEST 5: No is_detecting method")
			
			success_rate = tests_passed / total_tests
			logger.info(f"🧪 VERIFY_RESULT: {tests_passed}/{total_tests} tests passed ({success_rate:.1%})")
			
			if success_rate >= 0.6:  # 60% or better
				logger.info("✅ VERIFY_SUCCESS: Ball detector appears functional")
				return True
			else:
				logger.error("❌ VERIFY_FAIL: Ball detector appears non-functional")
				return False
				
		except Exception as e:
			logger.error(f"❌ Error verifying ball detector: {e}")
			return False
	
	
	def _create_new_ball_detector(self):
		"""Create new ball detector when none exists"""
		try:
			logger.info("🆕 CREATE_NEW: Creating new ball detector")
			
			# Method 1: Use parent setup method
			if hasattr(self.parent, 'setup_ball_detector'):
				if self.parent.setup_ball_detector():
					logger.info("✅ CREATE_SUCCESS: New detector via parent setup")
					return True
			
			# Method 2: Direct creation
			try:
				from active_ball_detector import ActiveBallDetector
				if hasattr(self.parent, 'machine'):
					self.parent.ball_detector = ActiveBallDetector(self, self.parent.machine)
					logger.info("✅ CREATE_SUCCESS: New detector via direct creation")
					return True
			except ImportError:
				logger.error("❌ Cannot import ActiveBallDetector")
			
			# Method 3: Force parent to recreate
			if hasattr(self.parent, 'machine'):
				# Clear any existing detector
				if hasattr(self.parent, 'ball_detector'):
					self.parent.ball_detector = None
				
				# Try setup again
				if hasattr(self.parent, 'setup_ball_detector'):
					return self.parent.setup_ball_detector()
			
			logger.error("❌ CREATE_FAIL: All methods failed")
			return False
			
		except Exception as e:
			logger.error(f"❌ Error creating new ball detector: {e}")
			return False
	
	
	def _emergency_ball_detector_recreation(self):
		"""Emergency recreation when all else fails"""
		try:
			logger.info("🚨 EMERGENCY: Starting emergency ball detector recreation")
			
			# Complete cleanup
			if hasattr(self.parent, 'ball_detector'):
				old_detector = self.parent.ball_detector
				
				# Try to stop gracefully
				if hasattr(old_detector, 'stop_detection'):
					try:
						old_detector.stop_detection()
					except:
						pass
				
				# Clear reference
				self.parent.ball_detector = None
				del old_detector
			
			# Wait for cleanup
			time.sleep(1.0)
			
			# Try multiple creation approaches
			success = False
			
			# Approach 1: Standard creation
			if not success:
				success = self._create_new_ball_detector()
			
			# Approach 2: Force import and create
			if not success:
				try:
					import importlib
					ball_detector_module = importlib.import_module('active_ball_detector')
					ActiveBallDetector = getattr(ball_detector_module, 'ActiveBallDetector')
					
					if hasattr(self.parent, 'machine'):
						self.parent.ball_detector = ActiveBallDetector(self, self.parent.machine)
						success = True
						logger.info("✅ EMERGENCY_SUCCESS: Detector created via force import")
				except Exception as e:
					logger.error(f"❌ Force import failed: {e}")
			
			# Approach 3: Create minimal detector
			if not success:
				try:
					class EmergencyBallDetector:
						def __init__(self, game, machine):
							self.game = game
							self.machine = machine
							self.suspended = False
							self.detection_active = False
							self.detection_thread = None
							self._start_emergency_detection()
						
						def _start_emergency_detection(self):
							def detection_loop():
								import RPi.GPIO as GPIO
								pin = 9  # Default ball detection pin
								threshold = 10
								
								while not self.suspended and self.game.is_game_active():
									try:
										# Simple ball detection
										if GPIO.input(pin):
											# Ball detected, process it
											if hasattr(self.machine, 'process_throw'):
												result = self.machine.process_throw()
												if self.game and hasattr(self.game, 'process_ball'):
													self.game.process_ball(result)
											time.sleep(1.0)  # Prevent multiple detections
										time.sleep(0.1)
									except Exception as e:
										logger.error(f"Emergency detection error: {e}")
										time.sleep(1.0)
							
							self.detection_thread = threading.Thread(target=detection_loop, daemon=True)
							self.detection_thread.start()
							self.detection_active = True
						
						def set_suspended(self, state):
							self.suspended = state
						
						def is_detecting(self):
							return self.detection_active and not self.suspended
					
					self.parent.ball_detector = EmergencyBallDetector(self, self.parent.machine)
					success = True
					logger.info("✅ EMERGENCY_SUCCESS: Minimal detector created")
					
				except Exception as e:
					logger.error(f"❌ Emergency minimal detector failed: {e}")
			
			if success:
				logger.info("✅ EMERGENCY_COMPLETE: Ball detector recreated")
				return True
			else:
				logger.error("❌ EMERGENCY_FAILED: Could not recreate ball detector")
				return False
				
		except Exception as e:
			logger.error(f"❌ Error in emergency recreation: {e}")
			return False
	
	
	def _start_detection_for_detector(self, detector):
		"""Start detection thread for a detector"""
		try:
			logger.info("🚀 START_DETECTION: Starting detection thread")
			
			# Stop any existing thread
			if hasattr(detector, 'detection_thread') and detector.detection_thread:
				if detector.detection_thread.is_alive():
					detector.stop_flag = True
					detector.detection_thread.join(timeout=2.0)
			
			# Reset flags
			detector.stop_flag = False
			detector.suspended = False
			
			# Create detection thread
			def detection_loop():
				import RPi.GPIO as GPIO
				
				# Get pin from settings or use default
				pin = 9  # Default ball detection pin
				try:
					with open('settings.json') as f:
						import json
						lane_settings = json.load(f)
						lane_id = lane_settings.get("Lane", "5")
						pin = int(lane_settings.get(lane_id, {}).get("ball_detector_pin", 9))
				except:
					logger.warning("Could not load ball detector pin from settings, using default")
				
				threshold = 10
				logger.info(f"🎯 DETECTION_THREAD: Starting on GPIO pin {pin}, threshold {threshold}")
				
				while not detector.stop_flag and not detector.suspended:
					try:
						if not self.is_game_active():
							time.sleep(0.5)
							continue
						
						# Check for ball detection
						if GPIO.input(pin):
							logger.info("🎯 BALL_DETECTED: Processing ball detection")
							
							# Call machine to process the throw
							if hasattr(detector, 'machine') and detector.machine:
								try:
									result = detector.machine.process_throw()
									logger.info(f"🎯 MACHINE_RESULT: {result}")
									
									# Call game to process the ball
									if detector.game and hasattr(detector.game, 'process_ball'):
										detector.game.process_ball(result)
										logger.info("🎯 BALL_PROCESSED: Ball sent to game")
									else:
										logger.error("❌ No game or process_ball method")
										
								except Exception as e:
									logger.error(f"❌ Error processing throw: {e}")
							else:
								logger.error("❌ No machine available for ball processing")
							
							# Wait to prevent multiple detections
							time.sleep(1.0)
						
						time.sleep(0.1)  # Small delay to prevent high CPU usage
						
					except Exception as e:
						logger.error(f"❌ Error in detection loop: {e}")
						time.sleep(1.0)
				
				logger.info("🛑 DETECTION_THREAD: Detection loop ended")
			
			# Start the thread
			detector.detection_thread = threading.Thread(target=detection_loop, daemon=True)
			detector.detection_thread.start()
			
			logger.info("✅ START_DETECTION_SUCCESS: Detection thread started")
			return True
			
		except Exception as e:
			logger.error(f"❌ Error starting detection: {e}")
			return False
	
	
	def _force_restart_detection_thread(self, detector):
		"""Force restart the detection thread"""
		try:
			logger.info("🔥 FORCE_RESTART: Force restarting detection thread")
			
			# Stop existing thread forcefully
			if hasattr(detector, 'detection_thread') and detector.detection_thread:
				detector.stop_flag = True
				if detector.detection_thread.is_alive():
					detector.detection_thread.join(timeout=3.0)
					if detector.detection_thread.is_alive():
						logger.warning("⚠️ Thread did not stop gracefully")
			
			# Clear thread reference
			detector.detection_thread = None
			
			# Start new detection
			return self._start_detection_for_detector(detector)
			
		except Exception as e:
			logger.error(f"❌ Error in force restart: {e}")
			return False
	
	
	def _verify_detection_working(self, detector):
		"""Verify that detection is actually working"""
		try:
			logger.info("🧪 VERIFY_DETECTION: Testing detection functionality")
			
			tests_passed = 0
			total_tests = 4
			
			# Test 1: Thread exists and is alive
			if hasattr(detector, 'detection_thread') and detector.detection_thread:
				if detector.detection_thread.is_alive():
					tests_passed += 1
					logger.info("✅ VERIFY_TEST 1: Detection thread is alive")
				else:
					logger.error("❌ VERIFY_TEST 1: Detection thread is not alive")
			else:
				logger.error("❌ VERIFY_TEST 1: No detection thread")
			
			# Test 2: is_detecting method works
			if hasattr(detector, 'is_detecting'):
				try:
					if detector.is_detecting():
						tests_passed += 1
						logger.info("✅ VERIFY_TEST 2: is_detecting() returns True")
					else:
						logger.error("❌ VERIFY_TEST 2: is_detecting() returns False")
				except Exception as e:
					logger.error(f"❌ VERIFY_TEST 2: is_detecting() error: {e}")
			else:
				logger.error("❌ VERIFY_TEST 2: No is_detecting method")
			
			# Test 3: Not suspended
			if hasattr(detector, 'suspended'):
				if not detector.suspended:
					tests_passed += 1
					logger.info("✅ VERIFY_TEST 3: Detector not suspended")
				else:
					logger.error("❌ VERIFY_TEST 3: Detector is suspended")
			else:
				tests_passed += 1  # Assume good if no suspension
				logger.info("✅ VERIFY_TEST 3: No suspension property (assumed good)")
			
			# Test 4: Stop flag not set
			if hasattr(detector, 'stop_flag'):
				if not detector.stop_flag:
					tests_passed += 1
					logger.info("✅ VERIFY_TEST 4: Stop flag not set")
				else:
					logger.error("❌ VERIFY_TEST 4: Stop flag is set")
			else:
				tests_passed += 1  # Assume good if no stop flag
				logger.info("✅ VERIFY_TEST 4: No stop flag (assumed good)")
			
			success_rate = tests_passed / total_tests
			logger.info(f"🧪 VERIFY_RESULT: {tests_passed}/{total_tests} tests passed ({success_rate:.1%})")
			
			return success_rate >= 0.75  # 75% success rate required
			
		except Exception as e:
			logger.error(f"❌ Error verifying detection: {e}")
			return False
	
	
	def _emergency_detection_restart(self, detector):
		"""Emergency restart as last resort"""
		try:
			logger.info("🚨 EMERGENCY_RESTART: Starting emergency detection restart")
			
			# Complete cleanup
			detector.stop_flag = True
			if hasattr(detector, 'detection_thread') and detector.detection_thread:
				if detector.detection_thread.is_alive():
					detector.detection_thread.join(timeout=2.0)
			
			detector.detection_thread = None
			time.sleep(0.5)
			
			# Recreate with enhanced capabilities
			self._enhance_detector_with_detection(detector)
			
			# Start detection
			success = self._start_detection_for_detector(detector)
			
			if success:
				# Final verification
				time.sleep(1.0)
				if self._verify_detection_working(detector):
					logger.info("✅ EMERGENCY_SUCCESS: Detection restarted")
					return True
			
			logger.error("❌ EMERGENCY_FAILED: Could not restart detection")
			return False
			
		except Exception as e:
			logger.error(f"❌ Emergency restart error: {e}")
			return False
	
	
	# Updated team movement process that uses the enhanced restoration
	def _process_team_move_with_thread_fix(self, data):
		"""FIXED: Process team move with enhanced ball detector thread management"""
		try:
			logger.info("🚀 TEAM_MOVE_THREAD_FIX: Starting team movement with thread fix")
			
			# Step 1: Preserve ball detector state
			ball_detector_preserved = self._preserve_ball_detector_state()
			
			# Step 2: Clear and rebuild game state
			self.bowlers = []
			self._safe_clear_widgets()
			self._reconstruct_bowlers_from_data(data)
			
			# Step 3: Reset game state
			self.current_bowler_index = 0
			self.ui_needs_rebuild = True
			
			# Step 4: Force UI manager reinitialization
			if hasattr(self, 'ui_manager'):
				self.ui_manager.ui_initialized = False
			
			# Step 5: Update UI
			self.update_ui()
			
			# Step 6: CRITICAL - Use enhanced restoration with thread fix
			if ball_detector_preserved:
				success = self._restore_ball_detector_state_with_thread_fix(ball_detector_preserved)
				if success:
					logger.info("✅ Ball detector successfully restored with thread fix")
				else:
					logger.error("❌ Ball detector restoration failed, attempting recreation")
					self._emergency_ball_detector_recreation()
			else:
				logger.info("🔧 No ball detector to preserve, creating new one")
				self._create_new_ball_detector()
			
			# Step 7: Final verification with detailed check
			if hasattr(self.parent, 'ball_detector') and self.parent.ball_detector:
				final_verification = self._verify_detection_working(self.parent.ball_detector)
				if final_verification:
					logger.info("🎯 FINAL_CHECK: Ball detection is fully operational")
				else:
					logger.error("🎯 FINAL_CHECK: Ball detection is NOT operational")
					# One more emergency attempt
					self._emergency_detection_restart(self.parent.ball_detector)
			
			# Step 8: Update displays
			if hasattr(self.parent, 'set_game_display') and self.bowlers:
				current_bowler = self.bowlers[self.current_bowler_index]
				self.parent.set_game_display(f"League: {current_bowler.name}")
			
			logger.info(f"✅ TEAM_MOVE_COMPLETE: {[b.name for b in self.bowlers]}")
			return True
			
		except Exception as e:
			logger.error(f"❌ Error in team move with thread fix: {e}")
			return False
	
	
	# Diagnostic function to check ball detector status
	def check_ball_detector_status(self):
		"""Check and log current ball detector status"""
		logger.info("🔍 BALL_DETECTOR_STATUS: Checking current status")
		
		if not hasattr(self.parent, 'ball_detector'):
			logger.error("❌ No ball_detector attribute on parent")
			return False
		
		if not self.parent.ball_detector:
			logger.error("❌ ball_detector is None")
			return False
		
		detector = self.parent.ball_detector
		logger.info(f"✅ Ball detector exists: {type(detector).__name__}")
		
		# Check key properties
		if hasattr(detector, 'game'):
			if detector.game == self:
				logger.info("✅ Game reference correct")
			else:
				logger.error(f"❌ Game reference wrong: {type(detector.game)} vs {type(self)}")
		
		if hasattr(detector, 'suspended'):
			logger.info(f"🔍 Suspended: {detector.suspended}")
		
		if hasattr(detector, 'detection_thread'):
			if detector.detection_thread:
				logger.info(f"🔍 Thread alive: {detector.detection_thread.is_alive()}")
			else:
				logger.error("❌ No detection thread")
		
		if hasattr(detector, 'is_detecting'):
			if callable(detector.is_detecting):
				logger.info(f"🔍 Is detecting: {detector.is_detecting()}")
		
		return True
	
	def _enhance_detector_with_detection(self, detector):
		"""Add detection capabilities to a detector that lacks them"""
		try:
			logger.info("🔧 ENHANCE: Adding detection capabilities to detector")
			
			# Add missing properties
			if not hasattr(detector, 'detection_thread'):
				detector.detection_thread = None
			
			if not hasattr(detector, 'suspended'):
				detector.suspended = False
			
			if not hasattr(detector, 'stop_flag'):
				detector.stop_flag = False
			
			# Add is_detecting method
			if not hasattr(detector, 'is_detecting'):
				def is_detecting_method():
					return (hasattr(detector, 'detection_thread') and 
						   detector.detection_thread is not None and 
						   detector.detection_thread.is_alive() and 
						   not getattr(detector, 'suspended', True))
				detector.is_detecting = is_detecting_method
			
			# Add start_detection method
			if not hasattr(detector, 'start_detection'):
				def start_detection_method():
					return self._start_detection_for_detector(detector)
				detector.start_detection = start_detection_method
			
			# Add set_suspended method
			if not hasattr(detector, 'set_suspended'):
				def set_suspended_method(state):
					detector.suspended = state
					if state:  # If suspending, stop detection
						detector.stop_flag = True
					else:  # If resuming, restart detection
						detector.stop_flag = False
						if not detector.is_detecting():
							detector.start_detection()
				detector.set_suspended = set_suspended_method
			
			logger.info("✅ ENHANCE_COMPLETE: Detector enhanced with detection capabilities")
			
		except Exception as e:
			logger.error(f"❌ Error enhancing detector: {e}")

			
	def _safely_suspend_ball_detector(self):
		"""Safely suspend ball detector without errors"""
		try:
			if hasattr(self.parent, 'ball_detector') and self.parent.ball_detector:
				logger.info("Suspending ball detector before team movement")
				
				# Multiple ways to suspend for safety
				if hasattr(self.parent.ball_detector, 'set_suspended'):
					self.parent.ball_detector.set_suspended(True)
					logger.info("Ball detector suspended via set_suspended")
				
				if hasattr(self.parent.ball_detector, 'stop_detection'):
					self.parent.ball_detector.stop_detection()
					logger.info("Ball detector stopped via stop_detection")
				
				# Store reference for later reactivation
				self._ball_detector_was_active = True
			else:
				self._ball_detector_was_active = False
				logger.info("No ball detector found to suspend")
				
		except Exception as e:
			logger.error(f"Error suspending ball detector: {e}")
			self._ball_detector_was_active = False
	
	
	def _enhanced_reconnect_ball_detector(self):
		"""ENHANCED: Reconnect ball detector with multiple fallback methods"""
		try:
			logger.info("Enhanced ball detector reconnection starting")
			
			# Method 1: Update existing ball detector
			if hasattr(self.parent, 'ball_detector') and self.parent.ball_detector:
				logger.info("Method 1: Updating existing ball detector reference")
				
				# Update the game reference
				self.parent.ball_detector.game = self
				
				# Ensure it's active
				if hasattr(self.parent.ball_detector, 'set_suspended'):
					self.parent.ball_detector.set_suspended(False)
					logger.info("Ball detector reactivated via set_suspended(False)")
				
				if hasattr(self.parent.ball_detector, 'start_detection'):
					self.parent.ball_detector.start_detection()
					logger.info("Ball detector restarted via start_detection()")
				
				# Test the connection
				if hasattr(self.parent.ball_detector, 'is_active'):
					if self.parent.ball_detector.is_active():
						logger.info("✅ Ball detector successfully reconnected (Method 1)")
						return True
			
			# Method 2: Use parent's setup method
			if hasattr(self.parent, 'setup_ball_detector'):
				logger.info("Method 2: Using parent's setup_ball_detector method")
				success = self.parent.setup_ball_detector()
				if success:
					logger.info("✅ Ball detector successfully created (Method 2)")
					return True
			
			# Method 3: Create new ball detector directly
			try:
				logger.info("Method 3: Creating new ball detector directly")
				from active_ball_detector import ActiveBallDetector
				
				if hasattr(self.parent, 'machine'):
					self.parent.ball_detector = ActiveBallDetector(self, self.parent.machine)
					logger.info("✅ Ball detector successfully created (Method 3)")
					return True
			except ImportError:
				logger.warning("ActiveBallDetector not available for Method 3")
			
			# Method 4: Force recreation through system
			logger.info("Method 4: Forcing complete ball detector recreation")
			if hasattr(self.parent, 'ball_detector'):
				# Clear old detector
				del self.parent.ball_detector
				self.parent.ball_detector = None
			
			# Try setup again
			if hasattr(self.parent, 'setup_ball_detector'):
				success = self.parent.setup_ball_detector()
				if success:
					logger.info("✅ Ball detector successfully recreated (Method 4)")
					return True
			
			logger.error("❌ All ball detector reconnection methods failed")
			return False
			
		except Exception as e:
			logger.error(f"Error in enhanced ball detector reconnection: {e}")
			return False
			
	def _reconnect_ball_detector(self):
		"""Reconnect ball detector to the updated game state"""
		try:
			if hasattr(self.parent, 'ball_detector') and self.parent.ball_detector:
				logger.info("Reconnecting ball detector to updated league game")
				
				# Update the ball detector's game reference
				self.parent.ball_detector.game = self
				
				# Ensure ball detector is active
				if hasattr(self.parent.ball_detector, 'set_suspended'):
					self.parent.ball_detector.set_suspended(False)
				
				logger.info("Ball detector reconnected successfully")
			else:
				# Ball detector doesn't exist, create a new one
				logger.info("Ball detector not found, creating new one")
				if hasattr(self.parent, 'setup_ball_detector'):
					self.parent.setup_ball_detector()
				
		except Exception as e:
			logger.error(f"Error reconnecting ball detector: {e}")
			# Try to create a new ball detector as fallback
			try:
				if hasattr(self.parent, 'setup_ball_detector'):
					logger.info("Attempting to create new ball detector as fallback")
					self.parent.setup_ball_detector()
			except Exception as fallback_error:
				logger.error(f"Fallback ball detector creation failed: {fallback_error}")
	
	def _safe_clear_widgets(self):
		"""Safely clear widgets without Tkinter errors"""
		try:
			if not hasattr(self, 'frame') or not self.frame:
				return
			
			# Get list of children first, then destroy them safely
			children = list(self.frame.winfo_children())
			
			for widget in children:
				try:
					if widget.winfo_exists():  # Check if widget still exists
						widget.destroy()
				except tk.TclError as e:
					logger.warning(f"Error destroying widget: {e}")
					continue
				except Exception as e:
					logger.warning(f"Unexpected error destroying widget: {e}")
					continue
			
			# Force update to ensure destruction is complete
			self.frame.update_idletasks()
			
		except Exception as e:
			logger.error(f"Error in safe widget clearing: {e}")
	
	def _reconstruct_bowlers_from_data(self, data):
		"""Reconstruct bowlers from team data"""
		for bowler_data in data.get("bowlers", []):
			bowler = Bowler(
				name=bowler_data["name"],
				frames=[],  # Initialize empty, will populate below
				current_frame=bowler_data["current_frame"],
				total_score=bowler_data["total_score"],
				handicap=bowler_data["handicap"]
			)
			
			# Set league-specific attributes
			bowler.average = bowler_data.get("average", 0)
			bowler.absent = bowler_data.get("absent", False)
			bowler.default_score = bowler_data.get("default_score", 0)
			
			# Reconstruct frames properly
			for frame_data in bowler_data["frames"]:
				frame = Frame(
					balls=[],  # Initialize empty, will populate below
					total=frame_data["total"],
					is_strike=frame_data["is_strike"],
					is_spare=frame_data["is_spare"]
				)
				
				# Reconstruct balls within the frame
				for ball_data in frame_data["balls"]:
					ball = BallResult(
						pin_config=ball_data["pin_config"],
						symbol=ball_data["symbol"],
						value=ball_data["value"]
					)
					frame.balls.append(ball)  # Add ball to frame.balls
				
				bowler.frames.append(frame)  # Add frame to bowler.frames
			
			self.bowlers.append(bowler)
	
	def _recover_from_team_move_error(self, data):
		"""Recovery function if team move fails"""
		logger.info("Attempting recovery from team move error")
		
		try:
			# Try to at least update the bowler data without UI changes
			self.bowlers = []
			self._reconstruct_bowlers_from_data(data)
			self.current_bowler_index = 0
			
			# Try a simple UI update
			if hasattr(self, 'parent') and hasattr(self.parent, 'set_game_display'):
				current_bowler = self.bowlers[0] if self.bowlers else None
				if current_bowler:
					self.parent.set_game_display(f"League: {current_bowler.name}")
			
			logger.info("Recovery successful - bowler data updated")
			
		except Exception as e:
			logger.error(f"Recovery failed: {e}")
	
	def _process_deferred_team_move(self, data):
		"""Process team move after waiting UI has completed"""
		logger.info("Processing deferred team move")
		self._showing_waiting_ui = False  # Clear the waiting flag
		self._process_team_move_immediate(data)
	
	def _process_team_move_immediate(self, data):
		"""Actually process the team move data"""
		# Clear current UI and bowlers
		self.bowlers = []
		
		# Reconstruct bowlers from team data (your existing logic)
		for bowler_data in data.get("bowlers", []):
			bowler = Bowler(
				name=bowler_data["name"],
				frames=[],
				current_frame=bowler_data["current_frame"],
				total_score=bowler_data["total_score"],
				handicap=bowler_data["handicap"]
			)
			
			# Set league-specific attributes
			bowler.average = bowler_data.get("average", 0)
			bowler.absent = bowler_data.get("absent", False)
			bowler.default_score = bowler_data.get("default_score", 0)
			
			# Reconstruct frames properly
			for frame_data in bowler_data["frames"]:
				frame = Frame(
					balls=[],
					total=frame_data["total"],
					is_strike=frame_data["is_strike"],
					is_spare=frame_data["is_spare"]
				)
				
				# Reconstruct balls within the frame
				for ball_data in frame_data["balls"]:
					ball = BallResult(
						pin_config=ball_data["pin_config"],
						symbol=ball_data["symbol"],
						value=ball_data["value"]
					)
					frame.balls.append(ball)
				
				bowler.frames.append(frame)
			
			self.bowlers.append(bowler)
		
		# Set current bowler to first in team
		self.current_bowler_index = 0
		self.ui_needs_rebuild = True
		
		# Update UI to show returned team
		self.update_ui()
		
		logger.info(f"Team received: {[b.name for b in self.bowlers]}")
	
	def handle_bowler_move(self, data):
		"""Handle individual bowler movement (legacy support)"""
		# Convert to team move format for consistency
		team_data = {
			"bowlers": [data],
			"from_lane": data.get("from_lane"),
			"to_lane": self.lane_id
		}
		self.handle_team_move(team_data)
	
	def handle_pair_ready(self, data):
		"""Handle paired lane ready notification"""
		from_lane = data.get("lane_id")
		if from_lane == self.paired_lane:
			logger.info(f"Paired lane {from_lane} is ready")
			self.pair_ready = True
			
			if self.wait_for_pair and not self.game_started:
				logger.info("Both lanes ready, starting game")
				self.practice_mode = False
				self.game_started = True
				self.update_ui()
	
	def handle_frame_update(self, data):
		"""Handle frame updates from paired lane"""
		logger.info(f"Frame update from paired lane: {data}")
		# Could be used for live scoring updates
	
	def handle_game_complete(self, data):
		"""Handle game completion from paired lane"""
		logger.info(f"Game complete notification: {data}")
		game_number = data.get("game_number", 0)
		
		if self.current_game_number > game_number:
			return
		
		if self.game_started and not data.get("force_end", False):
			logger.info(f"Paired lane completed game {game_number}")
			return
		
		if data.get("swap_bowlers", False) and game_number < self.settings.total_games:
			self._prepare_for_next_game()
			
	def handle_end_game_request(self, force_end=True, reason="Server request"):
		"""Handle end game request for this specific game instance"""
		logger.info(f"Game received end game request - Force: {force_end}, Reason: {reason}")
		
		try:
			# Save current game data if not forced
			if not force_end:
				try:
					self._save_current_game_data()
					logger.info("Game data saved before forced ending")
				except Exception as e:
					logger.warning(f"Could not save game data: {e}")
			
			# Stop all timers
			self._stop_all_timers()
			
			# Update displays
			if hasattr(self.parent, 'set_game_display'):
				self.parent.set_game_display(f"Game Ended: {reason}")
			
			if hasattr(self.parent, 'set_scroll_message'):
				self.parent.set_scroll_message(f"Game ended by server: {reason}")
			
			# Call the normal end game process
			self._end_game()
			
			# Set flag to indicate this was a forced end
			self.forced_end = True
			self.end_reason = reason
			
			logger.info(f"Game ended successfully - Reason: {reason}")
			
		except Exception as e:
			logger.error(f"Error in game end game request handler: {e}")
			# Fallback: just set game_started to False
			self.game_started = False
	
	def _stop_all_timers(self):
		"""Stop all running timers in the game"""
		try:
			# Stop main timer
			if hasattr(self, 'timer_running'):
				self.timer_running = False
			
			# Stop practice timer (for league games)
			if hasattr(self, 'practice_timer_label') and self.practice_timer_label:
				self.practice_timer_label = None
			
			# Stop next game countdown
			if hasattr(self, 'next_game_countdown_seconds'):
				self.next_game_countdown_seconds = 0
			
			# Clear any after() scheduled calls
			if hasattr(self, 'frame') and self.frame:
				# Unfortunately, we can't easily cancel all after() calls
				# but setting timer_running to False should stop most loops
				pass
			
			logger.info("All game timers stopped")
			
		except Exception as e:
			logger.error(f"Error stopping timers: {e}")
	
	def _notify_paired_lane_ready(self):
		"""Notify paired lane that this lane is ready"""
		if not self.paired_lane:
			return
		
		ready_data = {
			"lane_id": self.lane_id,
			"paired_lane": self.paired_lane
		}
		
		try:
			if hasattr(self.parent, 'send_to_lane'):
				self.parent.send_to_lane(self.paired_lane, 'pair_ready', ready_data)
				logger.info(f"Sent ready notification to lane {self.paired_lane}")
		except Exception as e:
			logger.error(f"Error sending ready notification: {e}")
	
	def _calculate_poa(self, bowler: Bowler):
		"""Calculate Pins Over Average for a bowler"""
		if not hasattr(bowler, 'average') or bowler.average == 0:
			return 0
		
		current_total = bowler.total_score
		frames_played = sum(1 for frame in bowler.frames if frame.balls)
		
		if frames_played == 0:
			return 0
		
		# Calculate expected score based on average
		expected_total = (bowler.average / 10) * frames_played
		poa = current_total - expected_total
		
		return round(poa)
	
	def update_ui(self):
		"""OPTIMIZED: UI update for league games with performance improvements"""
		if self.practice_mode:
			return  # Practice UI is handled separately
		
		if not self.game_started:
			return
		
		# PERFORMANCE: Check if UI rebuild is actually needed
		current_bowler_count = len(self.bowlers)
		ui_rebuild_needed = (
			self.ui_needs_rebuild or 
			current_bowler_count != self.last_bowler_count or
			not hasattr(self.ui_manager, 'ui_initialized') or
			not self.ui_manager.ui_initialized
		)
		
		if ui_rebuild_needed:
			logger.info("UI rebuild required for league game")
			self.ui_manager.ui_initialized = False
			self.ui_needs_rebuild = False
			self.last_bowler_count = current_bowler_count
		
		# PERFORMANCE: Batch POA calculations for all bowlers
		poa_start = time.time()
		for bowler in self.bowlers:
			bowler.poa = self._calculate_poa(bowler)
		logger.info(f"POA calculations completed in {time.time() - poa_start:.3f}s")
		
		# Update UI manager with current settings
		self.ui_manager.total_display_mode = self.total_display_mode
		self.ui_manager.bowlers = self.bowlers
		
		# PERFORMANCE: Single render call
		render_start = time.time()
		if self.bowlers and self.current_bowler_index < len(self.bowlers):
			self.ui_manager.render(self.current_bowler_index, self.hold_active)
		logger.info(f"League UI render completed in {time.time() - render_start:.3f}s")
		
		# PERFORMANCE: Batch display updates
		if hasattr(self.parent, 'set_game_display') and self.bowlers:
			current_bowler = self.bowlers[self.current_bowler_index]
			self.parent.set_game_display(f"League: {current_bowler.name}")
	
	
class LeagueUIManager(GameUIManager):
	
	def __init__(self, frame, bowlers: List[Bowler], settings: GameSettings, parent=None):
		super().__init__(frame, bowlers, settings, parent)
		self.total_display_mode = getattr(settings, 'total_display', 'regular')
		self.team_totals_created = False
		self._league_cache = {}
		self._last_team_total = None
	
	def _update_bowler_data(self, current_bowler_index):
		"""Enhanced bowler data update with league-specific total displays"""
		logger.info(f"League UI update with total_display_mode: {self.total_display_mode}")
		
		for bowler_idx, bowler in enumerate(self.bowlers):
			# Highlight current bowler
			if bowler_idx < len(self.bowler_name_labels):
				if bowler_idx == current_bowler_index and not getattr(bowler, 'game_completed', False):
					self.bowler_name_labels[bowler_idx].config(bg="yellow", fg="black")
				elif getattr(bowler, 'game_completed', False):
					self.bowler_name_labels[bowler_idx].config(bg="green", fg="white")
				else:
					self.bowler_name_labels[bowler_idx].config(
						bg=self.settings.background_color,
						fg=self.settings.foreground_color
					)
			
			# Update frame displays
			for frame_idx in range(len(bowler.frames)):
				if bowler_idx >= len(self.ball_labels) or frame_idx >= len(self.ball_labels[bowler_idx]):
					continue
				
				frame = bowler.frames[frame_idx]
				
				# Ball display (same as QuickGame)
				ball_display_text = ""
				if hasattr(frame, 'balls') and frame.balls:
					display_parts = []
					is_tenth_frame = (frame_idx == 9)
					
					for ball_idx, ball in enumerate(frame.balls):
						symbol_text = ball.symbol
						if self._ball_used_as_bonus(bowler, frame_idx, ball_idx):
							symbol_text += "*"
						display_parts.append(symbol_text)
					
					# Add bonus balls if enabled
					if getattr(self.settings, 'show_bonus_in_frame', True) and len(frame.balls) > 0:
						if frame.is_strike and not is_tenth_frame:
							bonus_balls = self._get_strike_bonus_balls_for_display(bowler, frame_idx)
							for bonus_ball in bonus_balls:
								display_parts.append(bonus_ball.symbol)
						elif frame.is_spare and not is_tenth_frame:
							bonus_ball = self._get_spare_bonus_ball_for_display(bowler, frame_idx)
							if bonus_ball:
								display_parts.append(bonus_ball.symbol)
					
					ball_display_text = " ".join(display_parts)
				
				self.ball_labels[bowler_idx][frame_idx].config(text=ball_display_text)
				
				# Frame total display (same as QuickGame)
				total_display = ""
				if hasattr(frame, 'total') and frame.total > 0:
					if getattr(self.settings, 'strike_streak_mode', False) and frame.is_strike:
						if self._is_strike_in_active_streak(bowler, frame_idx):
							total_display = "X"
						else:
							total_display = str(frame.total)
					else:
						total_display = str(frame.total)
				
				self.total_labels[bowler_idx][frame_idx].config(text=total_display)
			
			# ENHANCED: League-specific total column display
			if bowler_idx < len(self.bowler_total_labels):
				self._update_league_total_display(bowler_idx, bowler)
		
		# Add team totals row if not exists
		self._ensure_team_totals_row()
	
	def _update_league_total_display(self, bowler_idx, bowler):
		"""OPTIMIZED: Update total column with caching"""
		# PERFORMANCE: Cache key for this bowler's total display
		cache_key = f"{bowler_idx}_{bowler.total_score}_{getattr(bowler, 'handicap', 0)}_{getattr(bowler, 'poa', 0)}"
		
		# PERFORMANCE: Skip update if cached and unchanged
		if cache_key in self._league_cache:
			return
		
		self._league_cache[cache_key] = True
		
		total_widget = self.bowler_total_labels[bowler_idx]
		
		# PERFORMANCE: Only clear and rebuild if widget type changed
		if not isinstance(total_widget, tk.Frame):
			# Replace label with frame for complex layout
			parent = total_widget.master
			row = total_widget.grid_info()['row']
			column = total_widget.grid_info()['column']
			
			total_widget.destroy()
			total_frame = tk.Frame(
				parent,
				bg=self.settings.background_color,
				borderwidth=1,
				relief="solid"
			)
			total_frame.grid(row=row, column=column, padx=2, pady=2, sticky="nsew")
			self.bowler_total_labels[bowler_idx] = total_frame
			total_widget = total_frame
		else:
			# PERFORMANCE: Clear existing widgets efficiently
			for widget in total_widget.winfo_children():
				widget.destroy()
		
		# Get values
		regular_total = bowler.total_score
		handicap = getattr(bowler, 'handicap', 0)
		handicap_total = regular_total + handicap
		average = getattr(bowler, 'average', 0)
		poa = getattr(bowler, 'poa', 0)
		poa_sign = "+" if poa >= 0 else ""
		
		# PERFORMANCE: Create widgets based on display mode with minimal overhead
		if self.total_display_mode == "regular":
			self._create_simple_total_display(total_widget, str(regular_total))
		elif self.total_display_mode == "handicap":
			self._create_simple_total_display(total_widget, str(handicap_total))
		elif self.total_display_mode == "reg_mix":
			self._create_simple_total_display(total_widget, f"{regular_total}  ({handicap_total})", font_size=32)
		elif self.total_display_mode == "poa":
			self._create_poa_total_display(total_widget, regular_total, poa, poa_sign)
		elif self.total_display_mode == "all":
			self._create_full_total_display(total_widget, regular_total, handicap_total, average, poa, poa_sign)
	
	'''
	def _update_league_total_display(self, bowler_idx, bowler):
		"""Update total column with league-specific display modes"""
		total_widget = self.bowler_total_labels[bowler_idx]
		
		# Clear existing content
		for widget in total_widget.winfo_children():
			widget.destroy()
		
		# Configure the total widget as a frame for complex layouts
		if not isinstance(total_widget, tk.Frame):
			# Replace label with frame for complex layout
			parent = total_widget.master
			row = total_widget.grid_info()['row']
			column = total_widget.grid_info()['column']
			
			total_widget.destroy()
			total_frame = tk.Frame(
				parent,
				bg=self.settings.background_color,
				borderwidth=1,
				relief="solid"
			)
			total_frame.grid(row=row, column=column, padx=2, pady=2, sticky="nsew")
			self.bowler_total_labels[bowler_idx] = total_frame
			total_widget = total_frame
		
		# Get values
		regular_total = bowler.total_score
		handicap = getattr(bowler, 'handicap', 0)
		handicap_total = regular_total + handicap
		average = getattr(bowler, 'average', 0)
		poa = getattr(bowler, 'poa', 0)
		poa_sign = "+" if poa >= 0 else ""
		
		# Create layout based on display mode
		if self.total_display_mode == "regular":
			# Simple total display
			tk.Label(
				total_widget,
				text=str(regular_total),
				bg=self.settings.background_color,
				fg=self.settings.foreground_color,
				font=("Arial", 40, "bold")
			).pack(expand=True)
		
		elif self.total_display_mode == "handicap":
			# Handicap total only
			tk.Label(
				total_widget,
				text=str(handicap_total),
				bg=self.settings.background_color,
				fg=self.settings.foreground_color,
				font=("Arial", 40, "bold")
			).pack(expand=True)
		
		elif self.total_display_mode == "reg_mix":
			# Total with handicap in brackets
			display_text = f"{regular_total}  ({handicap_total})"
			tk.Label(
				total_widget,
				text=display_text,
				bg=self.settings.background_color,
				fg=self.settings.foreground_color,
				font=("Arial", 32, "bold")
			).pack(expand=True)
		
		elif self.total_display_mode == "poa":
			# Total with POA above
			top_frame = tk.Frame(total_widget, bg=self.settings.background_color)
			top_frame.pack(fill=tk.X)
			
			# POA display
			tk.Label(
				top_frame,
				text=f"POA: {poa_sign}{poa}",
				bg=self.settings.background_color,
				fg=self.settings.foreground_color,
				font=("Arial", 28)
			).pack()
			
			# Total display
			tk.Label(
				total_widget,
				text=str(regular_total),
				bg=self.settings.background_color,
				fg=self.settings.foreground_color,
				font=("Arial", 64, "bold")
			).pack(expand=True)
		
		elif self.total_display_mode == "all":
			# Complete layout: AVG, POA, Total, (Total+HDCP)
			# Top row frame
			top_frame = tk.Frame(total_widget, bg=self.settings.background_color)
			top_frame.pack(fill=tk.X, pady=(2, 0))
			
			# Top left: AVG
			tk.Label(
				top_frame,
				text=f"AVG: {average}",
				bg=self.settings.background_color,
				fg=self.settings.foreground_color,
				font=("Arial", 28),
				anchor="w"
			).pack(side=tk.LEFT)
			
			# Top right: POA
			tk.Label(
				top_frame,
				text=f"POA: {poa_sign}{poa}",
				bg=self.settings.background_color,
				fg=self.settings.foreground_color,
				font=("Arial", 28),
				anchor="e"
			).pack(side=tk.RIGHT)
			
			# Bottom row frame
			bottom_frame = tk.Frame(total_widget, bg=self.settings.background_color)
			bottom_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 2))
			
			# Bottom left: Regular Total
			tk.Label(
				bottom_frame,
				text=str(regular_total),
				bg=self.settings.background_color,
				fg=self.settings.foreground_color,
				font=("Arial", 72, "bold"),
				anchor="w"
			).pack(side=tk.LEFT, expand=True)
			
			# Bottom right: Handicap Total
			tk.Label(
				bottom_frame,
				text=f"({handicap_total})",
				bg=self.settings.background_color,
				fg=self.settings.foreground_color,
				font=("Arial", 72, "bold"),
				anchor="e"
			).pack(side=tk.RIGHT, expand=True)
	'''
	
	
	def _ensure_team_totals_row(self):
		"""Ensure team totals row exists at bottom"""
		if not hasattr(self, 'team_totals_created') or not self.team_totals_created:
			self._create_team_totals_row()
			self.team_totals_created = True
	
	def _create_team_totals_row(self):
		"""Create team totals row at bottom of display"""
		row_number = len(self.bowlers) + 1
		
		# Team totals label
		team_label = tk.Label(
			self.frame,
			text="TEAM TOTALS",
			bg="darkblue",
			fg="white",
			font=("Arial", 32, "bold"),
			borderwidth=1,
			relief="solid"
		)
		team_label.grid(row=row_number, column=0, padx=2, pady=2, sticky="nsew")
		
		# Empty frames for frame columns
		for col in range(1, 11):
			empty_frame = tk.Frame(
				self.frame,
				bg=self.settings.background_color,
				borderwidth=1,
				relief="solid"
			)
			empty_frame.grid(row=row_number, column=col, padx=2, pady=2, sticky="nsew")
		
		# Team total column
		team_total_frame = tk.Frame(
			self.frame,
			bg="darkblue",
			borderwidth=1,
			relief="solid"
		)
		team_total_frame.grid(row=row_number, column=11, padx=2, pady=2, sticky="nsew")
		
		# Calculate team totals
		regular_team_total = sum(bowler.total_score for bowler in self.bowlers)
		handicap_team_total = sum(bowler.total_score + getattr(bowler, 'handicap', 0) for bowler in self.bowlers)
		
		# Display based on total display mode
		if self.total_display_mode in ["regular"]:
			tk.Label(
				team_total_frame,
				text=str(regular_team_total),
				bg="darkblue",
				fg="white",
				font=("Arial", 40, "bold")
			).pack(expand=True)
		
		elif self.total_display_mode == "handicap":
			tk.Label(
				team_total_frame,
				text=str(handicap_team_total),
				bg="darkblue",
				fg="white",
				font=("Arial", 40, "bold")
			).pack(expand=True)
		
		elif self.total_display_mode in ["reg_mix", "poa", "all"]:
			# Show both totals
			top_frame = tk.Frame(team_total_frame, bg="darkblue")
			top_frame.pack(fill=tk.X)
			
			bottom_frame = tk.Frame(team_total_frame, bg="darkblue")
			bottom_frame.pack(fill=tk.BOTH, expand=True)
			
			# Regular total
			tk.Label(
				top_frame,
				text=f"REG: {regular_team_total}",
				bg="darkblue",
				fg="white",
				font=("Arial", 24, "bold")
			).pack()
			
			# Handicap total
			tk.Label(
				bottom_frame,
				text=f"HDCP: {handicap_team_total}",
				bg="darkblue",
				fg="white",
				font=("Arial", 24, "bold")
			).pack()
		
		# Store reference for updates
		self.team_total_frame = team_total_frame
		
	def _create_simple_total_display(self, parent, text, font_size=40):
		"""PERFORMANCE: Simple total display creation"""
		tk.Label(
			parent,
			text=text,
			bg=self.settings.background_color,
			fg=self.settings.foreground_color,
			font=("Arial", font_size, "bold")
		).pack(expand=True)
	
	def _create_poa_total_display(self, parent, regular_total, poa, poa_sign):
		"""PERFORMANCE: POA total display creation"""
		# POA label
		tk.Label(
			parent,
			text=f"POA: {poa_sign}{poa}",
			bg=self.settings.background_color,
			fg=self.settings.foreground_color,
			font=("Arial", 28)
		).pack()
		
		# Total label
		tk.Label(
			parent,
			text=str(regular_total),
			bg=self.settings.background_color,
			fg=self.settings.foreground_color,
			font=("Arial", 64, "bold")
		).pack(expand=True)
	
	def _create_full_total_display(self, parent, regular_total, handicap_total, average, poa, poa_sign):
		"""PERFORMANCE: Full total display creation"""
		# Top row frame
		top_frame = tk.Frame(parent, bg=self.settings.background_color)
		top_frame.pack(fill=tk.X, pady=(2, 0))
		
		# Top labels
		tk.Label(
			top_frame,
			text=f"AVG: {average}",
			bg=self.settings.background_color,
			fg=self.settings.foreground_color,
			font=("Arial", 28),
			anchor="w"
		).pack(side=tk.LEFT)
		
		tk.Label(
			top_frame,
			text=f"POA: {poa_sign}{poa}",
			bg=self.settings.background_color,
			fg=self.settings.foreground_color,
			font=("Arial", 28),
			anchor="e"
		).pack(side=tk.RIGHT)
		
		# Bottom row frame
		bottom_frame = tk.Frame(parent, bg=self.settings.background_color)
		bottom_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 2))
		
		# Bottom labels
		tk.Label(
			bottom_frame,
			text=str(regular_total),
			bg=self.settings.background_color,
			fg=self.settings.foreground_color,
			font=("Arial", 72, "bold"),
			anchor="w"
		).pack(side=tk.LEFT, expand=True)
		
		tk.Label(
			bottom_frame,
			text=f"({handicap_total})",
			bg=self.settings.background_color,
			fg=self.settings.foreground_color,
			font=("Arial", 72, "bold"),
			anchor="e"
		).pack(side=tk.RIGHT, expand=True)

class GameSaver:
	def __init__(self, save_path: str = "saved_game.json"):
		self.save_path = Path(save_path)

	def save(self, game: 'QuickGame'):
		"""Save a game state to a JSON file."""
		data = {
			"settings": {
				"background_color": game.settings.background_color,
				"foreground_color": game.settings.foreground_color,
				"pin_values": game.settings.pin_values,
				"patterns": game.settings.patterns,
				"frames_per_turn": game.settings.frames_per_turn,
				"total_games": game.settings.total_games,
				"total_time": game.settings.total_time,
				"pre_bowl": game.settings.pre_bowl,
			},
			"bowlers": [
				{
					"name": b.name,
					"frames": [
						{
							"balls": [
								{"value": ball.value, "symbol": ball.symbol, "pin_config": ball.pin_config}
								for ball in frame.balls
							],
							"total": frame.total,
							"is_strike": getattr(frame, "is_strike", False),
							"is_spare": getattr(frame, "is_spare", False),
						}
						for frame in b.frames
					],
					"total_score": b.total_score,
					"current_frame": b.current_frame,
					"handicap": b.handicap,
					"fouls": b.fouls,
					"prize": b.prize
				}
				for b in game.bowlers
			],
			"current_bowler_index": game.current_bowler_index,
			"current_game_number": game.current_game_number,
			"hold_active": game.hold_active,
			"game_started": game.game_started
		}
		
		try:
			# Ensure parent directories exist
			self.save_path.parent.mkdir(parents=True, exist_ok=True)
			
			# Write data to file
			with open(self.save_path, 'w') as f:
				json.dump(data, f, indent=2)
				
			logger.info(f"Game saved to {self.save_path}")
			return True
		except Exception as e:
			logger.error(f"Error saving game: {str(e)}")
			return False

	def load(self, parent=None) -> Optional['QuickGame']:
		"""Load a game from a JSON file."""
		if not self.save_path.exists():
			logger.error(f"No saved game found at {self.save_path}")
			return None
			
		try:
			# Read data from file
			with open(self.save_path, 'r') as f:
				data = json.load(f)
			
			# Create settings object
			settings = GameSettings(
				background_color=data["settings"]["background_color"],
				foreground_color=data["settings"]["foreground_color"],
				pin_values=data["settings"]["pin_values"],
				patterns=data["settings"]["patterns"],
				frames_per_turn=data["settings"]["frames_per_turn"],
				total_games=data["settings"]["total_games"],
				total_time=data["settings"]["total_time"],
				pre_bowl=data["settings"]["pre_bowl"]
			)
			
			# Create a new game
			game = QuickGame(bowlers=[], settings=settings, parent=parent)
			
			# Restore bowlers
			game.bowlers = []
			for b_data in data["bowlers"]:
				bowler = Bowler(
					name=b_data["name"],
					frames=[],
					current_frame=b_data["current_frame"],
					total_score=b_data["total_score"],
					handicap=b_data.get("handicap", 0),
					fouls=b_data.get("fouls", 0),
					prize=b_data.get("prize", False)
				)
				
				# Restore frames
				for f_data in b_data["frames"]:
					frame = Frame(
						balls=[],
						total=f_data["total"],
						is_strike=f_data.get("is_strike", False),
						is_spare=f_data.get("is_spare", False)
					)
					
					# Restore balls
					for ball_data in f_data["balls"]:
						ball = BallResult(
							pin_config=ball_data["pin_config"],
							symbol=ball_data["symbol"],
							value=ball_data["value"]
						)
						frame.balls.append(ball)
						
					bowler.frames.append(frame)
					
				game.bowlers.append(bowler)
			
			# Restore game state
			game.current_bowler_index = data["current_bowler_index"]
			game.current_game_number = data["current_game_number"]
			game.hold_active = data.get("hold_active", False)
			game.game_started = data.get("game_started", True)
			
			# Setup UI manager
			game.ui_manager = GameUIManager(game.frame, game.bowlers, settings)
			game.ui_manager.set_button_callbacks(
				on_reset=game.reset_pins,
				on_skip=game.skip_bowler,
				on_hold=game.toggle_hold,
				on_settings=game.open_settings,
				on_pin_restore=game.pin_restore
			)
			
			# Update UI
			game.update_ui()
			
			logger.info(f"Game loaded from {self.save_path}")
			return game
			
		except Exception as e:
			logger.error(f"Error loading game: {str(e)}")
			return None# -*- coding: utf-8 -*-
		
class HangmanBowling(BaseGame):
	def __init__(self, bowlers: List[Dict], background_color: str, foreground_color: str, settings: GameSettings, paired_lane=None, parent=None):
		super().__init__()
		self.bowlers = [Bowler(name) for name in bowlers]
		self.background_color = background_color
		self.foreground_color = foreground_color
		self.current_bowler_index = 0
		self.game_started = False
		self.hangman_parts = [
			"head", "body", "right_arm", "left_arm", 
			"right_leg_to_knee", "left_leg_to_knee", 
			"right_bottom_leg_to_foot", "left_bottom_leg_to_foot"
		]
		self.hangman_states = {bowler.name: [] for bowler in self.bowlers}
		self.frame = None
		
		# Extract bowler names for parent constructor
		bowler_names = [b["name"] for b in bowlers]
		super().__init__(bowlers=bowler_names, settings=settings, parent=parent)
		
		# Override the bowlers list with proper handicaps, absent status, and default scores
		self.bowlers = []
		for b in bowlers:
			frames = [Frame(balls=[], total=0) for _ in range(10)]
			bowler = Bowler(
				name=b["name"], 
				handicap=b.get("handicap", 0), 
				frames=frames,
				absent=b.get("absent", False),
				default_score=b.get("default_score", 0)
			)
			
			# If bowler is absent and has a default score, pre-fill frames with that score
			if bowler.absent and bowler.default_score > 0:
				for frame in frames:
					# Create a default ball with the specified score
					ball = BallResult(
						pin_config=[0, 0, 0, 0, 0],  # Default pin config
						symbol=str(bowler.default_score),
						value=bowler.default_score
					)
					frame.balls.append(ball)
					frame.total = bowler.default_score
					
				# Mark all frames as complete
				bowler.current_frame = 10
				bowler.total_score = bowler.default_score * 10
				
			self.bowlers.append(bowler)
		
		# NEW: Add comprehensive bowler tracking for cross-lane games
		self.all_bowlers_data = {}  # Track all bowlers even when they move
		self.bowler_last_seen = {}  # Track when bowlers were last on this lane
		
		# Store initial bowler data
		for bowler in self.bowlers:
			self.all_bowlers_data[bowler.name] = {
				'frames': bowler.frames,
				'total_score': bowler.total_score,
				'current_frame': bowler.current_frame,
				'handicap': bowler.handicap,
				'last_lane': self.lane_id
			}
			self.bowler_last_seen[bowler.name] = time.time()
		
		self.paired_lane = paired_lane  # Reference to the paired lane's game
		self.practice_mode = not settings.get("skip_practice", False)  # Start in practice mode unless skipped
		self.practice_end_time = None  # Time when practice mode ends
		self.max_bowlers_on_screen = 8  # Maximum number of bowlers to display on the screen
		self.team_total = {"scratch": 0, "handicap": 0}  # Team total scores
		self.timer_container = None  # Container for practice timer
		self.practice_timer_label = None
		self.current_game_number = 1  # Track which game we're on
		self.lane_id = lane_settings["Lane"]  # Get lane ID from settings
		self.wait_for_pair = settings.get("wait_for_pair", False)  # Whether to wait for paired lane
		self.pair_ready = False  # Whether the paired lane is ready
		
		# Register additional event listeners for league play
		dispatcher.register_listener('bowler_move', self.handle_bowler_move)
		dispatcher.register_listener('frame_update', self.handle_frame_update)
		dispatcher.register_listener('game_complete', self.handle_game_complete)
		dispatcher.register_listener('pair_ready', self.handle_pair_ready)
		
		logger.info(f"LeagueGame initialized with {len(bowlers)} bowlers on lane {self.lane_id}, paired with lane {paired_lane}")

	def start(self):
		"""Start the Hangman Bowling game."""
		self.game_started = True
		self.update_ui()

	def process_ball(self, result: List[int]):
		"""Process a ball result for the current bowler."""
		if not self.game_started:
			return

		bowler = self.bowlers[self.current_bowler_index]
		if result == [0, 0, 0, 0, 0]:
			# Advance the hangman by 1 part for the current bowler
			if len(self.hangman_states[bowler.name]) < len(self.hangman_parts):
				self.hangman_states[bowler.name].append(self.hangman_parts[len(self.hangman_states[bowler.name])])
		elif result == [1, 1, 1, 1, 1]:
			# Advance the previous bowler by 1 part
			previous_bowler_index = (self.current_bowler_index - 1) % len(self.bowlers)
			previous_bowler = self.bowlers[previous_bowler_index]
			if len(self.hangman_states[previous_bowler.name]) < len(self.hangman_parts):
				self.hangman_states[previous_bowler.name].append(self.hangman_parts[len(self.hangman_states[previous_bowler.name])])

		# Check if the current bowler's hangman is complete
		if len(self.hangman_states[bowler.name]) >= len(self.hangman_parts):
			self._end_bowler_game(bowler)

		# Update the UI after processing the ball
		self.update_ui()

		# Move to the next bowler's turn
		self._next_turn()

	def _next_turn(self):
		"""Move to the next bowler's turn."""
		self.current_bowler_index = (self.current_bowler_index + 1) % len(self.bowlers)
		self.update_ui()

	def _end_bowler_game(self, bowler: Bowler):
		"""End the game for the bowler."""
		bowler.total_score = len(self.hangman_states[bowler.name])
		self.current_bowler_index = (self.current_bowler_index + 1) % len(self.bowlers)

		# Check if all but one bowler have completed their hangman
		active_bowlers = [b for b in self.bowlers if len(self.hangman_states[b.name]) < len(self.hangman_parts)]
		if len(active_bowlers) <= 1:
			self._end_game()

	def _end_game(self):
		"""End the game for all bowlers."""
		logger.info("Game Over")
		self.game_started = False
		self.update_ui()

	def update_ui(self):
		"""Update the UI to reflect the current game state."""
		if not self.frame:
			return

		# Clear the frame
		for widget in self.frame.winfo_children():
			widget.destroy()

		# Display the current bowler's hangman status
		current_bowler = self.bowlers[self.current_bowler_index]
		current_bowler_frame = tk.Frame(self.frame, bg=self.background_color)
		current_bowler_frame.grid(row=0, column=0, padx=10, pady=10)

		tk.Label(current_bowler_frame, text=current_bowler.name, bg="blue", fg=self.foreground_color, font=("Arial", 16)).pack()
		self._draw_hangman(current_bowler_frame, self.hangman_states[current_bowler.name])

		# Display other bowlers' hangman status
		for i, bowler in enumerate(self.bowlers):
			if bowler != current_bowler:
				bowler_frame = tk.Frame(self.frame, bg=self.background_color)
				bowler_frame.grid(row=0, column=i+1, padx=10, pady=10)

				tk.Label(bowler_frame, text=bowler.name, bg="yellow" if i == (self.current_bowler_index - 1) % len(self.bowlers) else self.background_color, fg=self.foreground_color, font=("Arial", 14)).pack()
				self._draw_hangman(bowler_frame, self.hangman_states[bowler.name])

	def _draw_hangman(self, frame, parts):
		"""Draw the hangman figure based on the parts."""
		hangman_canvas = tk.Canvas(frame, bg=self.background_color, width=100, height=200)
		hangman_canvas.pack()

		if "head" in parts:
			hangman_canvas.create_oval(30, 30, 70, 70, outline="black")  # Head
		if "body" in parts:
			hangman_canvas.create_line(50, 70, 50, 120, fill="black")  # Body
		if "right_arm" in parts:
			hangman_canvas.create_line(50, 80, 80, 100, fill="black")  # Right arm
		if "left_arm" in parts:
			hangman_canvas.create_line(50, 80, 20, 100, fill="black")  # Left arm
		if "right_leg_to_knee" in parts:
			hangman_canvas.create_line(50, 120, 80, 140, fill="black")  # Right leg to knee
		if "left_leg_to_knee" in parts:
			hangman_canvas.create_line(50, 120, 20, 140, fill="black")  # Left leg to knee
		if "right_bottom_leg_to_foot" in parts:
			hangman_canvas.create_line(80, 140, 80, 160, fill="black")  # Right bottom leg to foot
		if "left_bottom_leg_to_foot" in parts:
			hangman_canvas.create_line(20, 140, 20, 160, fill="black")  # Left bottom leg to foot