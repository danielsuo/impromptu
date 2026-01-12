"""Notification area component for Impromptu UI."""

from textual.widgets import Static


class NotificationArea(Static):
    """Custom notification area that shows history of messages."""
    
    MAX_MESSAGES = 3
    CHECK_INTERVAL = 0.5
    
    def __init__(self) -> None:
        super().__init__("", id="notification-area")
        self._messages: dict[int, tuple[str, float]] = {}
        self._next_id = 0
        self._check_timer = None
    
    def on_mount(self) -> None:
        self._check_timer = self.set_interval(self.CHECK_INTERVAL, self._check_expired)
    
    def show_message(self, message: str, duration: float = 5.0) -> None:
        import time
        msg_id = self._next_id
        self._next_id += 1
        expire_time = time.time() + duration
        self._messages[msg_id] = (message, expire_time)
        
        while len(self._messages) > self.MAX_MESSAGES:
            oldest_id = min(self._messages.keys())
            del self._messages[oldest_id]
        
        self._update_display()
    
    def _check_expired(self) -> None:
        import time
        now = time.time()
        expired = [msg_id for msg_id, (_, expire_time) in self._messages.items() if now >= expire_time]
        if expired:
            for msg_id in expired:
                del self._messages[msg_id]
            self._update_display()
    
    def _update_display(self) -> None:
        if self._messages:
            sorted_msgs = sorted(self._messages.items(), reverse=True)
            text = "\n".join(msg for _, (msg, _) in sorted_msgs)
            self.update(text)
            self.add_class("notification")
        else:
            self.update("")
            self.remove_class("notification")
        self.refresh()
