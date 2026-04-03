import sys
from src.podcast_automation.pipeline import AutomationPipeline

def main():
    """
    Main entry point for the Podcast Shorts Automation Pipeline.
    Supports --dry-run flag for testing without uploading.
    """
    dry_run = "--dry-run" in sys.argv
    
    pipeline = AutomationPipeline(dry_run=dry_run)
    pipeline.run()

if __name__ == "__main__":
    main()
