import sys
from src.podcast_automation.pipeline import AutomationPipeline

def main():
    """
    Main entry point for the Podcast Shorts Automation Pipeline.
    Supports:
      --dry-run    Test without uploading.
      --run-id ID  Resume a previous partial run (useful for local re-runs).
    """
    dry_run = "--dry-run" in sys.argv
    run_id = None
    if "--run-id" in sys.argv:
        idx = sys.argv.index("--run-id")
        if idx + 1 < len(sys.argv):
            run_id = sys.argv[idx + 1]

    pipeline = AutomationPipeline(dry_run=dry_run, run_id=run_id)
    pipeline.run()

if __name__ == "__main__":
    main()
