"""Explicit live-model smoke test. Uses the user's own native subscription sign-in."""
import asyncio
import json
from clara.config import Config, default_data
from clara.store import Store
from clara.agent import AgentManager
from clara.instance import single_instance


async def main(config):
    sample = config.workspace / 'clara-smoke' / 'moved-folder'
    sample.mkdir(parents=True, exist_ok=True)
    (sample / 'Sharma-engagement.txt').write_text('SYNTHETIC TEST ONLY\nClient: Rohit Sharma\nType: Engagement letter\nReference: CLARA-SMOKE-271\n', encoding='utf-8')
    store = Store(config.data / 'clara.sqlite3')
    cid = store.create_conversation('Synthetic document search test')['id']
    manager = AgentManager(config, store)
    job = store.create_job(cid, 'Use the find-client-document skill. Find the synthetic Rohit Sharma engagement letter under clara-smoke in your workspace, verify its reference, and attach the actual file. No browser or commands are needed.', 'ask', [])
    try:
        await manager.execute(job)
    except Exception as error:
        store.status(job['id'], 'failed', message=str(error))
    artifacts = store.rows("SELECT id,name,size FROM files WHERE job_id=? AND kind='artifact'", (job['id'],))
    result = {'status':store.job(job['id'])['status'], 'artifacts':artifacts,
              'passed':store.job(job['id'])['status']=='completed' and bool(artifacts)}
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['passed'] else 1)


if __name__ == '__main__':
    config = Config(default_data());config.initialize()
    with single_instance(config.data):
        asyncio.run(main(config))
