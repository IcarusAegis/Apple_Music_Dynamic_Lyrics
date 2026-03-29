import asyncio
import winrt.windows.media.control as wmc
from typing import Callable, Optional

class MediaListener:
    def __init__(self):
        self.session_manager: Optional[wmc.GlobalSystemMediaTransportControlsSessionManager] = None
        self.current_session: Optional[wmc.GlobalSystemMediaTransportControlsSession] = None
        
        # Callbacks
        self.on_song_changed: Optional[Callable[[str, str, str], None]] = None
        self.on_playback_state_changed: Optional[Callable[[str], None]] = None
        self.on_position_changed: Optional[Callable[[int], None]] = None  # Position in milliseconds

        self._session_changed_token = None
        self._media_props_changed_token = None
        self._playback_info_changed_token = None
        self._timeline_props_changed_token = None
        
        # Cache to prevent duplicate events
        self._last_title = None
        self._last_artist = None
        self._last_platform = None
        
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    async def start(self):
        """Initializes the media listener and starts listening to events."""
        self.loop = asyncio.get_running_loop()
        self.session_manager = await wmc.GlobalSystemMediaTransportControlsSessionManager.request_async()
        if not self.session_manager:
            print("Failed to get GlobalSystemMediaTransportControlsSessionManager")
            return

        self._session_changed_token = self.session_manager.add_current_session_changed(self._on_current_session_changed)
        await self._update_current_session(self.session_manager.get_current_session())

    async def _update_current_session(self, session: Optional[wmc.GlobalSystemMediaTransportControlsSession]):
        if self.current_session:
            # Remove old listeners
            if self._media_props_changed_token:
                self.current_session.remove_media_properties_changed(self._media_props_changed_token)
            if self._playback_info_changed_token:
                self.current_session.remove_playback_info_changed(self._playback_info_changed_token)
            if self._timeline_props_changed_token:
                self.current_session.remove_timeline_properties_changed(self._timeline_props_changed_token)

        self.current_session = session

        if self.current_session:
            # Add new listeners
            self._media_props_changed_token = self.current_session.add_media_properties_changed(self._on_media_properties_changed)
            self._playback_info_changed_token = self.current_session.add_playback_info_changed(self._on_playback_info_changed)
            self._timeline_props_changed_token = self.current_session.add_timeline_properties_changed(self._on_timeline_properties_changed)
            
            # Initial trigger
            await self._trigger_song_changed()
            self._trigger_playback_state_changed()
            self._trigger_position_changed()
        else:
            if self.on_song_changed:
                self.on_song_changed("", "")
            if self.on_playback_state_changed:
                self.on_playback_state_changed("Stopped")

    def _on_current_session_changed(self, sender, args):
        if self.loop:
            asyncio.run_coroutine_threadsafe(
                self._update_current_session(self.session_manager.get_current_session()), 
                self.loop
            )

    def _on_media_properties_changed(self, sender, args):
        if self.loop:
            asyncio.run_coroutine_threadsafe(self._trigger_song_changed(), self.loop)

    def _on_playback_info_changed(self, sender, args):
        if self.loop:
            self.loop.call_soon_threadsafe(self._trigger_playback_state_changed)

    def _on_timeline_properties_changed(self, sender, args):
        if self.loop:
            self.loop.call_soon_threadsafe(self._trigger_position_changed)

    async def _trigger_song_changed(self):
        if not self.current_session or not self.on_song_changed:
            return
        try:
            props = await self.current_session.try_get_media_properties_async()
            if props:
                title = props.title
                artist = props.artist
                platform = self.current_session.source_app_user_model_id or "Unknown"
                
                # print out for debug
                print(f"[MediaListener] Got properties: '{title}' - '{artist}' [{platform}]")
                print(f"[MediaListener] Last cached properties: '{self._last_title}' - '{self._last_artist}' [{self._last_platform}]")
                
                # Only trigger if it actually changed
                if title != self._last_title or artist != self._last_artist or platform != self._last_platform:
                    print(f"[MediaListener] Song or platform has changed! Emitting event...")
                    self._last_title = title
                    self._last_artist = artist
                    self._last_platform = platform
                    self.on_song_changed(title, artist, platform)
        except Exception as e:
            print(f"Error getting media properties: {e}")

    def _trigger_playback_state_changed(self):
        if not self.current_session or not self.on_playback_state_changed:
            return
        info = self.current_session.get_playback_info()
        if info:
            state = info.playback_status
            state_str = "Unknown"
            if state == wmc.GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING:
                state_str = "Playing"
            elif state == wmc.GlobalSystemMediaTransportControlsSessionPlaybackStatus.PAUSED:
                state_str = "Paused"
            elif state == wmc.GlobalSystemMediaTransportControlsSessionPlaybackStatus.STOPPED:
                state_str = "Stopped"
            self.on_playback_state_changed(state_str)

    def _trigger_position_changed(self):
        if not self.current_session or not self.on_position_changed:
            return
        timeline = self.current_session.get_timeline_properties()
        if timeline and timeline.position:
            position_ms = int(timeline.position.total_seconds() * 1000)
            self.on_position_changed(position_ms)

    def get_current_position(self) -> int:
        """Helper to get the current exact position without waiting for event."""
        if not self.current_session:
            return 0
        timeline = self.current_session.get_timeline_properties()
        if timeline and timeline.position:
            return int(timeline.position.total_seconds() * 1000)
        return 0


# Simple test block
async def main():
    listener = MediaListener()
    
    def on_song(title, artist, platform="Unknown"):
        print(f"[Event] Song Changed: {title} - {artist} [{platform}]")
        
    def on_playback(state):
        print(f"[Event] Playback State: {state}")
        
    def on_position(pos):
        print(f"[Event] Position: {pos} ms")

    listener.on_song_changed = on_song
    listener.on_playback_state_changed = on_playback
    listener.on_position_changed = on_position

    await listener.start()
    
    print("Listening to media events... Press Ctrl+C to stop.")
    try:
        # Keep the loop running
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    asyncio.run(main())
