from __future__ import annotations

import time
from typing import Callable

from amrte.operations.runtime import (
    ENVIRONMENT,
    VERSION,
    PersistentResearchRuntime,
)


RuntimeFactory = Callable[[], PersistentResearchRuntime]


def main(
    runtime_factory: RuntimeFactory = PersistentResearchRuntime,
) -> int:
    runtime = runtime_factory()
    exit_code = 0

    print("=" * 60)
    print("AMRTE RESEARCH RUNTIME")
    print(f"Version     : {VERSION}")
    print(f"Environment : {ENVIRONMENT}")
    print("Execution   : PROHIBITED")
    print("=" * 60)

    try:
        print("[STARTUP] Starting persistent research runtime...")

        runtime.start()

        print("[PERSISTENCE] Local checkpoint repository ready.")

        report = runtime.recovery_report

        if report is None:
            print(
                "[RECOVERY] No prior checkpoint. "
                "Starting new local research run."
            )
        else:
            checkpoint = report.checkpoint

            if checkpoint is not None:
                print(
                    "[RECOVERY] Checkpoint found: "
                    f"{checkpoint.checkpoint_id}"
                )

            print(
                f"[RECOVERY] Outcome: "
                f"{report.outcome.name}"
            )
            print(
                f"[RECOVERY] Confidence: "
                f"{report.confidence.name}"
            )
            print(
                f"[RECOVERY] Epoch: "
                f"{report.recovery_epoch}"
            )

        print(f"[RUNTIME] State: {runtime.state}")
        print(
            "[RUNTIME] AMRTE is running in "
            "local research mode."
        )
        print(
            "[RUNTIME] Financial execution "
            "is prohibited."
        )
        print(
            "[OBSERVABILITY] Persistent logging active."
        )
        print(
            "[RUNTIME] Press Ctrl+C "
            "to stop safely."
        )

        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print()
        print("[SHUTDOWN] Ctrl+C received.")

    except Exception as exc:
        print(
            f"[FATAL] {type(exc).__name__}: {exc}"
        )
        exit_code = 1

    finally:
        if runtime.engine is not None:
            try:
                print("[SHUTDOWN] Stopping AMRTE...")

                runtime.shutdown()

                if runtime.last_checkpoint is not None:
                    print(
                        "[CHECKPOINT] Saved: "
                        f"{runtime.last_checkpoint.checkpoint_id}"
                    )
                    print(
                        "[CHECKPOINT] Sequence: "
                        f"{runtime.last_checkpoint.sequence_number}"
                    )

                print(
                    f"[SHUTDOWN] State: "
                    f"{runtime.state}"
                )
                print("[SHUTDOWN] Complete.")

            except Exception as exc:
                print(
                    "[SHUTDOWN] Failure: "
                    f"{type(exc).__name__}: {exc}"
                )
                exit_code = 1

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())


