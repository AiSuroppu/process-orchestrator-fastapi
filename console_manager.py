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

    def print(self, process_name: str, message: str, prefix: str = ""):
        """
        The main method to print output in a context-aware manner.

        Args:
            process_name: The unique name of the source of the output.
            message: The raw content from stdout, which may include '\r' or '\n'.
            prefix: The formatted prefix (e.g., with colors) for the line.
        """
        with self._lock:
            # --- 1. Analyze the message's intent BEFORE cleaning it ---

            # An overwrite is intended if a carriage return is present.
            # We use `in` because buffering can cause multiple updates to be read
            # at once (e.g., "data1\rdata2"), where startswith() would fail.
            is_overwrite_intent = '\r' in message
            
            # The line is considered "finalized" if the child process sent a newline.
            # This is the most reliable signal that the cursor should move down.
            is_finalized_by_child = message.endswith('\n')

            # --- 2. Clean the message content for printing ---
            
            # Strip all leading/trailing whitespace AND control characters for the content.
            content = message.strip()
            
            # Do not process empty lines.
            if not content:
                return

            # --- 3. Handle context switching and finalize previous lines ---

            # If the process is changing and the previous line was left dangling,
            # we must print a newline to "commit" it and prevent the new log
            # from overwriting it.
            if self._last_process_name is not None and self._last_process_name != process_name:
                if self._last_line_was_dangling:
                    print()

            # --- 4. Render the output based on intent ---

            if is_overwrite_intent:
                # For overwrites, move the cursor to the start of the line (\r)
                # and print the new content.
                # \033[K is an ANSI escape code to clear the rest of the line,
                # crucial for when the new line is shorter than the old one.
                print(f"\r{prefix}{content}\033[K", end="", flush=True)
            else:
                # For standard logs, just print the content.
                # We don't add a newline here yet; we let the finalization step handle it.
                print(f"{prefix}{content}", end="", flush=True)

            # --- 5. Finalize the current line and update state ---

            if is_finalized_by_child:
                # The child process sent a newline, so we honor it,
                # moving the cursor to the next line for future output.
                print()
                self._last_line_was_dangling = False
            else:
                # The child did not send a newline. The line is left dangling,
                # waiting to be either overwritten or finalized later.
                self._last_line_was_dangling = True

            # Update the name of the last process that printed.
            self._last_process_name = process_name

# Create a single, global instance to be used across the application
console_manager = ConsoleManager()