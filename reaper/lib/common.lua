local json = require('dkjson')
local M = {}
function M.object(t) return setmetatable(t or {}, {__jsontype='object'}) end
function M.array(t) return setmetatable(t or {}, {__jsontype='array'}) end
function M.encode(t) return assert(json.encode(t)) end
function M.decode(s)
  assert(#s<=1048576,'JSON exceeds size limit')
  local v,pos,err=json.decode(s,1,json.null)
  assert(not err and not s:sub(pos):find('%S'),'Invalid JSON: '..tostring(err))
  return v
end
function M.read(path)
  local f=assert(io.open(path,'rb')); local s=f:read(1048577); f:close(); return M.decode(s)
end
function M.exists(path) local f=io.open(path,'rb'); if f then f:close();return true end return false end
function M.id() return reaper.genGuid():gsub('[{}-]','') end
function M.write(path,value)
  assert(not M.exists(path),'Immutable destination exists: '..path)
  local tmp=path..'.'..M.id()..'.tmp'
  local f=assert(io.open(tmp,'wb')); assert(f:write(M.encode(value))); assert(f:flush()); assert(f:close())
  local ok,err=os.rename(tmp,path); assert(ok,'Rename failed: '..tostring(err))
end
function M.copy(t) return M.decode(M.encode(t)) end
function M.equal(a,b)
  if type(a)~=type(b) then return false end
  if type(a)~='table' then return a==b end
  for k,v in pairs(a) do if not M.equal(v,b[k]) then return false end end
  for k in pairs(b) do if a[k]==nil then return false end end
  return true
end
function M.q(n) assert(n==n and math.abs(n)<1e15,'Invalid number'); return math.floor(n*1000000+0.5) end
function M.note_less(a,b) for i=1,7 do if a[i]~=b[i] then return a[i]<b[i] end end return false end
-- Match unchanged notes first, then unambiguous edits sharing onset or pitch/channel.
-- This is receiver-local selection bookkeeping, never canonical identity or musical data.
function M.match_notes(old,new)
  local used,map={},{}
  for j,n in ipairs(new) do
    for i,o in ipairs(old) do if not used[i] and M.equal(o.note,n) then map[j]=i;used[i]=true;break end end
  end
  local function score(a,b)
    if a[5]~=b[5] and a[1]~=b[1] then return 0 end
    if a[1]~=b[1] and a[3]~=b[3] then return 0 end
    local s=0;for k=1,6 do if a[k]==b[k] then s=s+1 end end;return s
  end
  for j,n in ipairs(new) do if not map[j] then
    local best,bestscore,tied=nil,0,false
    for i,o in ipairs(old) do if not used[i] then
      local s=score(o.note,n)
      if s>bestscore then best=i;bestscore=s;tied=false elseif s==bestscore then tied=true end
    end end
    if best and not tied then
      local mutual=true
      for k,other in ipairs(new) do if k~=j and not map[k] and score(old[best].note,other)>=bestscore then mutual=false end end
      if mutual then map[j]=best;used[best]=true end
    end
  end end
  return map
end
function M.diff(before,after)
  if before.name~=after.name or before.volume~=after.volume or before.pan~=after.pan then
    return 'properties',M.object{name=after.name,volume=after.volume,pan=after.pan}
  end
  local ids={}; for id in pairs(before.items) do ids[#ids+1]=id end; table.sort(ids)
  for _,id in ipairs(ids) do if not after.items[id] then return 'delete_item',M.object{id=id} end end
  ids={}; for id in pairs(after.items) do ids[#ids+1]=id end; table.sort(ids)
  for _,id in ipairs(ids) do if not M.equal(before.items[id],after.items[id]) then return 'put_item',M.object{item=after.items[id]} end end
end
return M
