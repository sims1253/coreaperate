import json
import uuid
import pytest
from pathlib import Path
from lupa import LuaRuntime
from coreaperate.model import dumps
from coreaperate.spool import Spool
from .test_protocol import baseline


def runtime():
    lua=LuaRuntime(unpack_returned_tuples=True)
    lua.execute("package.path='reaper/lib/?.lua;'..package.path; reaper={genGuid=function() return 'unique-guid' end}; C=require('common'); E=require('engine')")
    lua.globals().fixture=dumps(baseline())
    return lua


def test_cross_language_unicode_integer_empty_containers():
    lua=runtime()
    encoded=lua.execute("return C.encode(C.decode(fixture))")
    assert json.loads(encoded)==baseline()
    assert lua.execute("return C.equal(C.decode(fixture),C.copy(C.decode(fixture)))")
    canonical=Path('fixtures/canonical.json').read_text(encoding='utf8')
    lua.globals().fixture=canonical
    assert json.loads(lua.execute('return C.encode(C.decode(fixture))'))==json.loads(canonical)


def test_lua_self_echo_newer_pending_and_selection_exclusion():
    lua=runtime()
    lua.execute('''
      local b=C.decode(fixture)
      e=E.new('A',b); e:snapshot({project=b,meta={drums={owner='A',revision=1,epoch=2},bass={owner='B',revision=1,epoch=2}},seq=2},b,function()error('unexpected apply')end)
      current=C.copy(b);current.tracks.drums.name='first'
      op=e:operation('drums','properties',{name='first',volume=1000000,pan=0},current)
      current.tracks.drums.name='second'
      after=C.copy(b.tracks.drums);after.name='first'
      local result=e:event({seq=3,id=op.id,actor='A',track='drums',kind='properties',before=b.tracks.drums,after=after,meta={owner='A',revision=2,epoch=2}},current,function()error('self echo overwrote local')end)
      assert(result=='applied' and current.tracks.drums.name=='second')
      assert(e.accepted.tracks.drums.name=='first' and e.flight.drums==nil)
      local kind,payload=C.diff(e.accepted.tracks.drums,current.tracks.drums)
      assert(kind=='properties' and payload.name=='second')
      assert(C.diff(b.tracks.bass,b.tracks.bass)==nil)
    ''')


def test_lua_divergence_gap_and_apply_failure():
    lua=runtime()
    lua.execute('''
      b=C.decode(fixture);e=E.new('A',b)
      e:snapshot({project=b,meta={drums={owner='A',revision=1,epoch=2},bass={owner='B',revision=1,epoch=2}},seq=2},b,function()end)
      c=C.copy(b);c.tracks.bass.name='unauthorized'
      assert(not pcall(function()e:check(c)end))
      assert(not pcall(function()e:snapshot({project=b},c,function()error('overwrite')end)end))
      assert(e:event({seq=4},b,function()end)=='gap')
      after=C.copy(b.tracks.bass);after.name='remote'
      assert(not pcall(function()e:event({seq=3,id='remote',actor='B',track='bass',kind='properties',before=b.tracks.bass,after=after,meta={}},b,function()error('partial apply')end)end))
      assert(e.seq==2 and e.accepted.tracks.bass.name=='Bass')
    ''')


def test_all_lua_files_compile():
    lua=runtime()
    for path in Path('reaper').rglob('*.lua'):
        lua.execute("assert(load(...))",path.read_text(encoding='utf8'))


def test_real_lua_python_spool_roundtrip(tmp_path):
    lua=runtime()
    api=lua.globals().reaper
    api.genGuid=lambda:uuid.uuid4().hex
    api.RecursiveCreateDirectory=lambda p,flags:Path(p).mkdir(parents=True,exist_ok=True)
    def enum(p,i):
        files=sorted(x.name for x in Path(p).iterdir() if x.is_file())
        return files[i] if i<len(files) else None
    api.EnumerateFiles=enum
    lua.globals().root=str(tmp_path)
    id_=lua.execute("s=require('spool').new(root,'from_bridge');return s:send(C.decode(fixture))")
    spool=Spool(tmp_path,'from_bridge')
    assert list(spool.pending())==[(id_,baseline())]
    spool.ack(id_)
    assert lua.execute("return #s:receive()")==0
    to_lua=Spool(tmp_path,'to_bridge')
    py_id=to_lua.send(baseline())
    lua.execute("r=require('spool').new(root,'to_bridge');local m=r:receive()[1];assert(C.equal(m.message,C.decode(fixture)));r:ack(m.id)")
    assert list(to_lua.pending())==[]
    assert (tmp_path/'to_bridge'/f'{py_id}.ack').exists()


def test_note_selection_matching_unchanged_and_unambiguous_edits():
    lua=runtime()
    lua.execute('''
      local a={0,1000000,60,90,0,0,0};local b={2000000,1000000,64,90,0,0,0}
      local old={{note=a,selected=true},{note=b,selected=false}}
      local changed=C.copy(a);changed[4]=100;changed[6]=1
      local added={4000000,500000,70,99,2,0,0}
      local matches=C.match_notes(old,{changed,b,added})
      assert(matches[1]==1 and matches[2]==2 and matches[3]==nil)
      local moved=C.copy(a);moved[1]=1000000
      assert(C.match_notes(old,{moved,b})[1]==1)
    ''')


@pytest.mark.parametrize('stored,effective,allowed', [(-1,3,True),(-1,0,True),(3,3,True),(0,0,True),(-1,5,False),(5,5,False),(6,6,False)])
def test_capture_resolves_inherited_pan_mode(stored,effective,allowed):
    """Exercise actual capture, including the default mode used by prepared tracks."""
    lua=runtime()
    lua.globals().stored_panmode=stored
    lua.globals().effective_panmode=effective
    lua.execute('''
      reaper.ValidatePtr=function() return true end
      reaper.GetPlayStateEx=function() return 0 end
      reaper.CountTempoTimeSigMarkers=function() return 0 end
      reaper.Master_GetPlayRate=function() return 1 end
      reaper.TimeMap_GetTimeSigAtTime=function() return 4,4,120 end
      reaper.GetProjExtState=function() return 1,'session' end
      reaper.CountTracks=function() return 1 end
      reaper.CountMediaItems=function() return 0 end
      reaper.GetTrack=function() return 'track-pointer' end
      reaper.GetTrackGUID=function() return 'drums' end
      reaper.GetMediaTrackInfo_Value=function(_,key)
        local values={I_FOLDERDEPTH=0,I_FREEMODE=0,B_MAINSEND=1,I_NCHAN=2,I_PANMODE=stored_panmode,D_VOL=1,D_PAN=0}
        return assert(values[key],key)
      end
      reaper.GetTrackUIPan=function() return true,0,0,effective_panmode end
      reaper.CountTrackEnvelopes=function() return 0 end
      reaper.GetTrackNumSends=function() return 0 end
      reaper.GetSetMediaTrackInfo_String=function() return true,'Drums' end
      reaper.CountTrackMediaItems=function() return 0 end
      capture_ok,capture_result=pcall(require('model').capture,'project-pointer')
    ''')
    assert lua.globals().capture_ok == allowed, str(lua.globals().capture_result)
