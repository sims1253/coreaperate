import asyncio
import copy
import json
import uuid
import pytest
from websockets.asyncio.server import serve
from websockets.asyncio.client import connect
from coreaperate.model import Invalid, digest, dumps, loads, project
from coreaperate.store import Store
from coreaperate.network import Coordinator
from coreaperate.spool import Spool


def baseline():
    return dict(session="session", config=dict(tempo=120000000,numerator=4,denominator=4),order=["drums","bass"],
                tracks={id_:dict(id=id_,name=name,volume=1000000,pan=0,items={}) for id_,name in [("drums","Drüms 🥁"),("bass","Bass")]})


def proposal(store, track="drums", type_="claim", payload=None, **extra):
    m=store.state["meta"][track]
    return dict(protocol=1,session="session",id=uuid.uuid4().hex,track=track,revision=m["revision"],epoch=m["epoch"],type=type_,payload=payload or {},**extra)


def properties(name):
    return dict(name=name,volume=123456,pan=-999999)


def test_concurrent_tracks_dedup_restart_undo(tmp_path):
    s=Store(tmp_path/"db",baseline())
    for actor,t in [("A","drums"),("B","bass")]:
        assert s.propose(actor,proposal(s,t))[1]
    a=proposal(s,"drums","properties",properties("new 🥁"))
    b=proposal(s,"bass","properties",properties("new bass"))
    ea,_=s.propose("A",a); eb,_=s.propose("B",b)
    assert s.state["seq"]==4
    assert s.propose("A",a)==(ea,False)
    conflict=copy.deepcopy(a);conflict["payload"]["name"]="collision"
    with pytest.raises(Invalid): s.propose("A",conflict)
    s.db.close();s=Store(tmp_path/"db",baseline())
    assert s.propose("A",a)==(ea,False)
    assert len(s.replay(2))==2
    assert s.propose("A",proposal(s,"drums","undo"))[1]
    assert s.state["project"]["tracks"]["bass"]["name"]=="new bass"
    assert s.propose("A",proposal(s,"drums","undo"))[0]["type"]=="rejected"


def test_ownership_and_malformed(tmp_path):
    s=Store(tmp_path/"db",baseline())
    claim=proposal(s); stale=proposal(s)
    assert s.propose("A",claim)[1]
    assert not s.propose("B",stale)[1]
    assert not s.propose("B",proposal(s,"drums","properties",properties("bad")))[1]
    edit=proposal(s,"drums","properties",properties("old"))
    assert s.propose("A",proposal(s,"drums","handover",dict(owner="B")))[1]
    assert not s.propose("A",edit)[1]
    before=dumps(s.state)
    malformed=proposal(s,"drums","properties",dict(name="x",volume=float('nan'),pan=0))
    with pytest.raises(ValueError): s.propose("B",malformed)
    assert dumps(s.state)==before
    for raw in ['{"x":1,"x":2}', '{"x":NaN}', '['*2000, ' '*1048577]:
        with pytest.raises(Invalid): loads(raw)


def test_identity_and_item_validation(tmp_path):
    s=Store(tmp_path/"db",baseline());s.propose("A",proposal(s))
    it=dict(id="item",take="take",position=1000000,length=250000,notes=[[0,2000000,60,127,15,1,0]])
    assert s.propose("A",proposal(s,"drums","put_item",dict(item=it)))[1]
    assert s.state["project"]["tracks"]["drums"]["items"]["item"]["notes"][0][1]==2000000
    bad=copy.deepcopy(it);bad["id"]="other"
    assert not s.propose("A",proposal(s,"drums","put_item",dict(item=bad)))[1]
    assert s.propose("A",proposal(s,"drums","delete_item",dict(id="item")))[1]
    assert s.propose("B",proposal(s,"bass"))[1]
    assert not s.propose("B",proposal(s,"bass","put_item",dict(item=it)))[1]


def test_rejected_outcome_survives_restart_and_stale_revision(tmp_path):
    s=Store(tmp_path/'db',baseline())
    op=proposal(s,'drums','properties',properties('unauthorized'))
    original,_=s.propose('B',op)
    assert original['type']=='rejected'
    s.db.close();s=Store(tmp_path/'db',baseline())
    assert s.propose('B',op)==(original,False)
    assert s.outcome('B',op)==original
    s.propose('A',proposal(s))
    stale=proposal(s,'drums','properties',properties('stale'))
    s.propose('A',proposal(s,'drums','properties',properties('new')))
    assert not s.propose('A',stale)[1]


def test_exclusive_companion_lock(tmp_path):
    from coreaperate.lock import instance_lock
    with instance_lock(tmp_path):
        with pytest.raises(OSError):
            with instance_lock(tmp_path):pass
    with instance_lock(tmp_path):pass


def test_spool_interrupted_and_restart(tmp_path):
    s=Spool(tmp_path,"from_bridge",2)
    (s.path/"interrupted.tmp").write_bytes(b'{')
    id_=s.send(dict(text="鼓 🥁",notes=[[1,2,60,90,0,0,0]]))
    received=list(Spool(tmp_path,"from_bridge").pending())
    assert len(received)==1 and received[0][0]==id_
    s.ack(id_);s.collect();assert list(s.pending())==[]
    s.send(received[0][1],id_);assert list(s.pending())==[]
    s.send({});s.send({})
    with pytest.raises(Invalid):s.send({})


def test_websocket_two_peers_reconnect_replay(tmp_path):
    async def run():
        s=Store(tmp_path/"db",baseline());co=Coordinator(s,{"A":"a"*40,"B":"b"*40})
        async with serve(co.handler,"127.0.0.1",0) as server:
            url=f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
            async def hello(ws,actor):
                await ws.send(dumps(dict(type="hello",protocol=1,client=actor,token=actor.lower()*40,session="session",baseline=digest(baseline()))))
                msg=loads(await ws.recv());assert msg["type"]=="snapshot"
            async def event(ws):
                while True:
                    msg=loads(await ws.recv())
                    if msg["type"]=="event":return msg
            async with connect(url,proxy=None) as a,connect(url,proxy=None) as b:
                await hello(a,"A");await hello(b,"B")
                await a.send(dumps(proposal(s)));await event(a);await event(b)
                await b.send(dumps(proposal(s,"bass")));await event(a);await event(b)
                pa=proposal(s,"drums","properties",properties("a"));pb=proposal(s,"bass","properties",properties("b"))
                await asyncio.gather(a.send(dumps(pa)),b.send(dumps(pb)))
                assert [ (await event(a))["seq"] for _ in range(2)]==[3,4]
                assert [ (await event(b))["seq"] for _ in range(2)]==[3,4]
            await asyncio.sleep(.02)
            async with connect(url,proxy=None) as a:
                await hello(a,"A")
                await a.send(dumps(dict(type="replay",after=2)))
                assert (await event(a))["seq"]==3
                assert (await event(a))["seq"]==4
    asyncio.run(run())
