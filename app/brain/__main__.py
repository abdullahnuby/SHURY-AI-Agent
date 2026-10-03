from __future__ import annotations
import argparse
import json

from app.brain import CognitiveKernel


def main() -> None:
    parser = argparse.ArgumentParser(description='SHURY V23 cognitive kernel')
    parser.add_argument('message', nargs='+')
    parser.add_argument('--session', default='brain-demo')
    parser.add_argument('--act', action='store_true')
    args = parser.parse_args()
    kernel = CognitiveKernel()
    message = ' '.join(args.message)
    result = kernel.act(message, session_id=args.session) if args.act else kernel.think(message, session_id=args.session)
    print(result.response)
    print(json.dumps(result.state.decision.to_dict() if result.state.decision else {}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
