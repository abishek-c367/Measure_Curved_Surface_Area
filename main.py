import argparse
import logging
from burnbuild.config import load_config
from burnbuild.pipeline import BurnBuildPipeline


def main():
    parser = argparse.ArgumentParser(description="BurnBuildSurface pipeline")
    parser.add_argument("command", choices=["prepare", "reconstruct", "all", "visualize"])
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    pipeline = BurnBuildPipeline(load_config(args.config))
    if args.command == "prepare":
        pipeline.prepare()
    elif args.command == "reconstruct":
        pipeline.reconstruct()
    elif args.command == "all":
        pipeline.prepare()
        pipeline.reconstruct()
    else:
        pipeline.visualize()


if __name__ == "__main__":
    main()
