class MockVisionService:
    def acknowledge_video_frame(self, frame_count: int) -> str:
        return f"mock video frame #{frame_count} received"
