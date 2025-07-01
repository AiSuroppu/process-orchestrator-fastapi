# console_manager.py
import threading
from typing import Optional

class ConsoleManager:
    """
    A thread-safe, stateful manager for printing to the console.
    It robustly handles interleaving logs from multiple processes, correctly
    interpreting terminal control characters like carriage returns ('\r') and
    newlines ('\n') to replicate the intended output of each process without
    visual corruption.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._last_process_name: Optional[str] = None
        # Tracks if the last printed line was left "dangling" without a newline,
        # typical for progress bars or other overwriting UI elements.
        self._last_line_was_dangling: bool = False
        # Buffer for incomplete messages from the raw stream
        self._message_buffer: str = ""

    def print(self, process_name: str, message_chunk: str, prefix: str = ""):
        """
        The main method to print output in a context-aware manner.

        Args:
            process_name: The unique name of the source of the output.
            message_chunk: A raw chunk of content from stdout, which may be partial.
            prefix: The formatted prefix (e.g., with colors) for the line.
        """
        with self._lock:
            # Append new chunk to the buffer and split into processable lines
            self._message_buffer += message_chunk
            # We split by \n to find complete lines. Any text after the last \n
            # is an incomplete line and becomes the new buffer.
            lines = self._message_buffer.split('\n')
            self._message_buffer = lines.pop() # Last element is the new buffer

            for message in lines:
                if not message: # Skip empty strings that can result from split
                    continue
                
                # Each "line" from the split is a complete thought from the child.
                # We add the newline back for our internal logic.
                self._print_single_message(process_name, message + '\n', prefix)
        
            # After processing complete lines, check if the remaining buffer
            # contains a carriage return, indicating a dangling progress bar update.
            if self._message_buffer and '\r' in self._message_buffer:
                # Process the dangling update, but don't clear the buffer yet.
                self._print_single_message(process_name, self._message_buffer, prefix)
                # If a progress bar update ends with \r, it gets processed,
                # and the buffer is effectively cleared on the next read.
                # A simple way to handle this is to treat it as processed and clear.
                self._message_buffer = self._message_buffer.split('\r')[-1]


    def _print_single_message(self, process_name: str, message: str, prefix: str = ""):
        """Processes a single, complete message or a dangling progress update."""
        # --- 1. Analyze the message's intent BEFORE cleaning it ---
        is_overwrite_intent = '\r' in message
        is_finalized_by_child = message.endswith('\n')

        # --- 2. Clean the message content for printing ---
        content = message.strip('\r\n')
        
        if not content:
            return

        # --- 3. Handle context switching and finalize previous lines ---
        if self._last_process_name is not None and self._last_process_name != process_name:
            if self._last_line_was_dangling:
                print()

        # --- 4. Render the output based on intent ---
        if is_overwrite_intent:
            print(f"\r{prefix}{content}\033[K", end="", flush=True)
        else:
            # For a dangling line (from the buffer), we might not have a newline.
            # Don't print a prefix if we're just continuing a line.
            # This logic assumes we're always starting a new prefixed line.
            print(f"{prefix}{content}", end="", flush=True)

        # --- 5. Finalize the current line and update state ---
        if is_finalized_by_child:
            print()
            self._last_line_was_dangling = False
        else:
            self._last_line_was_dangling = True

        self._last_process_name = process_name

# Create a single, global instance to be used across the application
console_manager = ConsoleManager()