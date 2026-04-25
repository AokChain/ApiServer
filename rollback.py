from server.services import BlockService
from server.sync import log_block, log_message
from pony import orm


TARGET_HEIGHT = 2778450
BATCH_SIZE = 100


@orm.db_session
def rollback_batch(target_height, batch_size):
    latest_block = BlockService.latest_block()

    if not latest_block or latest_block.height <= target_height:
        return latest_block.height if latest_block else None, 0

    deleted = 0

    while (
        latest_block
        and latest_block.height > target_height
        and deleted < batch_size
    ):
        log_block("Rolling back", latest_block)

        delete_block = latest_block
        latest_block = delete_block.previous_block

        delete_block.delete()
        orm.commit()

        deleted += 1

    height = latest_block.height if latest_block else None
    return height, deleted


@orm.db_session
def report_initial_state(target_height):
    latest = BlockService.latest_block()

    if not latest:
        log_message("No blocks in database")
        return False

    if latest.height <= target_height:
        log_message(
            f"Database height ({latest.height}) is already at or below "
            f"target ({target_height}); nothing to do"
        )
        return False

    log_message(
        f"Rolling back from {latest.height} to {target_height} "
        f"({latest.height - target_height} blocks)"
    )
    return True


def rollback(target_height):
    log_message(f"Starting rollback to height {target_height}")

    if not report_initial_state(target_height):
        return

    height = None
    while True:
        height, deleted = rollback_batch(target_height, BATCH_SIZE)
        if deleted == 0:
            break

    log_message(f"Rollback complete; final height: {height}")


if __name__ == "__main__":
    rollback(TARGET_HEIGHT)
