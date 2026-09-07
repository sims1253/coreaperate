"""Actual WebSocket + SQLite + disk spool. Musical adapter remains simulated here."""
import asyncio
import contextlib
import uuid
from websockets.asyncio.server import serve
from coreaperate.network import Coordinator, client
from coreaperate.store import Store
from coreaperate.spool import Spool
from .test_protocol import baseline, proposal, properties


def test_two_companions_real_spool_and_stale_offline_proposal(tmp_path):
    async def run():
        store=Store(tmp_path/'db',baseline())
        coordinator=Coordinator(store,{'A':'a'*40,'B':'b'*40})
        async with serve(coordinator.handler,'127.0.0.1',0) as server:
            url=f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}'
            tasks=[];out={};in_={}
            try:
                for actor in ['A','B']:
                    root=tmp_path/actor
                    out[actor]=Spool(root,'from_bridge');in_[actor]=Spool(root,'to_bridge')
                    tasks.append(asyncio.create_task(client(dict(url=url,client=actor,token=actor.lower()*40,ipc=str(root)))))
                    out[actor].send(dict(type='bridge_hello',baseline=baseline()))
                async def wait_for(actor,predicate):
                    async def poll():
                        while True:
                            for id_,message in in_[actor].pending():
                                in_[actor].ack(id_)
                                if predicate(message):return message
                            await asyncio.sleep(.01)
                    return await asyncio.wait_for(poll(),5)
                for actor in ['A','B']:
                    await wait_for(actor,lambda m:m['type']=='snapshot')
                    out[actor].send(dict(type='ready',seq=0))
                for actor,track in [('A','drums'),('B','bass')]:
                    out[actor].send(proposal(store,track))
                    for observer in ['A','B']:
                        await wait_for(observer,lambda m:m['type']=='event' and m['track']==track)
                edits=[proposal(store,'drums','properties',properties('local A')),proposal(store,'bass','properties',properties('local B'))]
                for actor,edit in zip(['A','B'],edits):out[actor].send(edit)
                for actor in ['A','B']:
                    for seq in [3,4]:
                        event=await wait_for(actor,lambda m:m['type']=='event')
                        assert event['seq']==seq
                assert store.state['project']['tracks']['drums']['name']=='local A'
                # Stop the client, put an unaccepted old proposal on disk, reconnect.
                tasks[0].cancel()
                with contextlib.suppress(asyncio.CancelledError):await tasks[0]
                await asyncio.sleep(.02)
                old=proposal(store,'drums','properties',properties('OFFLINE MUST NOT PUBLISH'))
                out['A'].send(old)
                out['A'].send(dict(type='bridge_hello',baseline=baseline()))
                tasks[0]=asyncio.create_task(client(dict(url=url,client='A',token='a'*40,ipc=str(tmp_path/'A'))))
                await wait_for('A',lambda m:m['type']=='snapshot')
                rejected=await wait_for('A',lambda m:m['type']=='rejected')
                assert rejected['id']==old['id']
                assert store.state['project']['tracks']['drums']['name']=='local A'
            finally:
                for task in tasks:task.cancel()
                await asyncio.gather(*tasks,return_exceptions=True)
    asyncio.run(run())
