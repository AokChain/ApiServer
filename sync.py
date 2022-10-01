from apscheduler.schedulers.blocking import BlockingScheduler
from server.sync import sync_blocks, sync_tokens
from server.sync import sync_ipfs_cache
from server.sync import sync_mempool

background = BlockingScheduler()
background.add_job(sync_ipfs_cache, "interval", minutes=10)
background.add_job(sync_tokens, "interval", seconds=30)
background.add_job(sync_blocks, "interval", seconds=5)
background.add_job(sync_mempool, "interval", seconds=15)
background.start()
