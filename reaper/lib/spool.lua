local C=require('common')
local M={}; M.__index=M
local sequence=0
function M.new(root,direction)
  local path=root..'/'..direction
  reaper.RecursiveCreateDirectory(path,0)
  return setmetatable({path=path},M)
end
function M:files()
  local out={};local i=0
  while true do
    local name=reaper.EnumerateFiles(self.path,i);if not name then break end;i=i+1
    if name:match('^[%w_-]+%.json$') then out[#out+1]=name end
  end
  table.sort(out);return out
end
function M:send(msg)
  local files=self:files();local count=0
  for _,name in ipairs(files) do
    if C.exists(self.path..'/'..name:gsub('%.json$','.ack')) then
      assert(os.remove(self.path..'/'..name))
    else count=count+1 end
  end
  assert(count<64,'IPC queue full; preserve/export and restart companion')
  sequence=sequence+1
  local id=string.format('%010d_%012d_',os.time(),sequence)..C.id();C.write(self.path..'/'..id..'.json',msg);return id
end
function M:receive()
  local out={}
  for _,name in ipairs(self:files()) do
    if not C.exists(self.path..'/'..name:gsub('%.json$','.ack')) then
      out[#out+1]={id=name:sub(1,-6),message=C.read(self.path..'/'..name)}
      if #out>=64 then break end
    end
  end
  return out
end
function M:ack(id)
  assert(id:match('^[%w_-]+$'))
  local path=self.path..'/'..id..'.ack';if not C.exists(path) then C.write(path,{applied=true}) end
end
return M
