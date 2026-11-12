-- Named projects over Omarchy's own per-monitor workspace mapping.
-- No workspace renumbering, background process, or replacement reconciler.
local M = {}
local config, by_id, by_slot = nil, {}, {}
local busy, settling, generation = false, false, 0
local selected, previous = nil, nil
local appearance_project, appearance_generation = nil, 0
local published_view = nil
local renderer_connected = false
local renderer_generation = 0

local function json_string(value)
  return '"' .. tostring(value):gsub('[%z\1-\31\\"]', function(char)
    if char == '"' then return '\\"' end
    if char == '\\' then return '\\\\' end
    return string.format('\\u%04x', char:byte())
  end) .. '"'
end

local function json_array(values)
  return '[' .. table.concat(values, ',') .. ']'
end

function M.request_appearance(project)
  if not config.appearance_request_file or not config.appearance_command or appearance_project == project.id then return end
  local path = config.appearance_request_file
  local file = assert(io.open(path .. '.tmp', 'w'))
  file:write('{"project":' .. json_string(project.id) .. ',"wallpaper_managed":'
    .. (renderer_connected and 'true' or 'false') .. '}\n')
  file:close()
  assert(os.rename(path .. '.tmp', path))
  appearance_project = project.id
  appearance_generation = appearance_generation + 1
  local pending = appearance_generation
  hl.timer(function()
    if pending == appearance_generation then hl.exec_cmd(config.appearance_command) end
  end, { type = 'oneshot', timeout = 100 })
end

function M.monitors()
  local result, seen = {}, {}
  local function add(monitor)
    if monitor and not monitor.is_mirror and not seen[monitor.name] then
      seen[monitor.name] = true
      result[#result + 1] = monitor
    end
  end
  if #config.monitors > 0 then
    for _, selector in ipairs(config.monitors) do add(hl.get_monitor(selector)) end
  else
    for _, monitor in ipairs(hl.get_monitors()) do add(monitor) end
  end
  return result
end

local function project_on(monitor)
  local active = monitor and monitor.active_workspace
  if not active or not active.id or active.id <= 0 then return nil end
  for _, project in ipairs(config.projects) do
    if active.id == o.workspaces.workspace_id(monitor, project.slot) then return project end
  end
end

function M.current()
  local focused = hl.get_active_monitor()
  if not focused then return nil end
  for _, monitor in ipairs(M.monitors()) do
    if monitor.name == focused.name then return project_on(monitor) end
  end
end

local function project_for(id)
  local project = by_id[id] or by_slot[tonumber(id)]
  assert(project, 'Unknown project: ' .. tostring(id))
  return project
end

function M.publish()
  if not config.state_file then return end
  local projects, monitors = {}, {}
  for _, project in ipairs(config.projects) do
    projects[#projects + 1] = '{"id":' .. json_string(project.id)
      .. ',"name":' .. json_string(project.name) .. ',"slot":' .. project.slot
      .. (project.icon and ',"icon":' .. json_string(project.icon) or '')
      .. (project.label and ',"label":' .. json_string(project.label) or '') .. '}'
  end
  for _, monitor in ipairs(M.monitors()) do
    local workspaces = {}
    for _, project in ipairs(config.projects) do
      workspaces[#workspaces + 1] = json_string(project.id) .. ':'
        .. o.workspaces.workspace_id(monitor, project.slot)
    end
    monitors[#monitors + 1] = '{"name":' .. json_string(monitor.name)
      .. ',"workspaces":{' .. table.concat(workspaces, ',') .. '}}'
  end
  local content = '{"version":1,"projects":' .. json_array(projects)
    .. ',"monitors":' .. json_array(monitors) .. '}\n'
  -- Active project highlighting comes from compositor events. Rewriting an
  -- unchanged model recreates every bar button and makes a switch flicker.
  if content ~= published_view then
    local file = assert(io.open(config.state_file .. '.tmp', 'w'))
    file:write(content)
    file:close()
    assert(os.rename(config.state_file .. '.tmp', config.state_file))
    published_view = content
  end
  if config.history_file and selected then
    local history = assert(io.open(config.history_file .. '.tmp', 'w'))
    history:write(selected.id .. '\n' .. (previous and previous.id or '') .. '\n')
    history:close()
    assert(os.rename(config.history_file .. '.tmp', config.history_file))
  end
end

local function synchronized(project)
  local monitors = M.monitors()
  if #monitors == 0 then return false end
  for _, monitor in ipairs(monitors) do
    if project_on(monitor) ~= project then return false end
  end
  return true
end

function M.renderer_ready(value)
  if renderer_connected ~= (value == true) then appearance_project = nil end
  renderer_connected = value == true
  local project = M.current()
  if project then M.request_appearance(project) end
end

local function forward_to_renderer(shortcut, fallback)
  renderer_generation = renderer_generation + 1
  local pending = renderer_generation
  hl.dispatch(hl.dsp.global('omarchy-projects:' .. shortcut))
  hl.timer(function()
    if renderer_generation ~= pending then return end
    -- A shell crash cannot strand the compositor's keyboard navigation.
    renderer_connected = false
    appearance_project = nil
    fallback()
  end, { type = 'oneshot', timeout = 1000 })
end

function M.show(id)
  local project = project_for(id)
  if config.preload_wallpapers and renderer_connected ~= false then
    forward_to_renderer('show-' .. project.slot, function() M.commit(project.id) end)
    return true
  end
  return M.commit(id)
end

function M.commit(id, managed)
  renderer_generation = renderer_generation + 1
  if type(managed) == 'boolean' and managed ~= renderer_connected then
    renderer_connected = managed
    appearance_project = nil
  end
  local project = project_for(id)
  local monitors = M.monitors()
  if #monitors == 0 then return false end
  local focused = hl.get_active_monitor()
  local origin = focused and focused.name
  local pointer = hl.get_cursor_pos()
  local old = M.current() or selected
  if old and old ~= project then previous = old end
  busy = true
  local ok, err = pcall(function()
    -- Switch the original monitor last: focus finishes on the same screen.
    for _, monitor in ipairs(monitors) do
      if monitor.name ~= origin then
        local active = monitor.active_workspace
        if not active or active.id ~= o.workspaces.workspace_id(monitor, project.slot) then
          o.workspaces.focus(project.slot, monitor.name)()
        end
      end
    end
    if origin then
      local managed = false
      for _, monitor in ipairs(monitors) do
        if monitor.name == origin then
          local active = monitor.active_workspace
          if not active or active.id ~= o.workspaces.workspace_id(monitor, project.slot) then
            o.workspaces.focus(project.slot, origin)()
          elseif hl.get_active_monitor().name ~= origin then
            hl.dispatch(hl.dsp.focus({ monitor = origin }))
          end
          managed = true
        end
      end
      if not managed and hl.get_monitor(origin) then
        hl.dispatch(hl.dsp.focus({ monitor = origin }))
      end
    end
  end)
  -- Omarchy's focus helper may warp to each monitor/workspace's focused
  -- window. Put the pointer back before this compositor event is presented,
  -- rather than changing the user's ordinary cursor-warp preferences.
  local pointer_ok, pointer_err = pcall(function()
    local current = pointer and hl.get_cursor_pos()
    if current and (current.x ~= pointer.x or current.y ~= pointer.y) then
      hl.dispatch(hl.dsp.cursor.move({ x = pointer.x, y = pointer.y }))
    end
  end)
  busy = false
  if not ok then error(err) end
  if not pointer_ok then error(pointer_err) end
  selected = project
  if managed == true then
    -- The shell may advance its shared wallpaper clock only after every
    -- monitor has committed its workspace change in this compositor event.
    hl.dispatch(hl.dsp.global('omarchy-projects:start-' .. project.slot))
  end
  M.publish()
  M.request_appearance(project)
  return true
end

function M.step(direction)
  if config.preload_wallpapers and renderer_connected ~= false then
    forward_to_renderer(direction > 0 and 'next' or 'prev', function() M.step(direction) end)
    return true
  end
  local current = M.current() or selected
  local index = direction > 0 and 0 or 1
  for position, project in ipairs(config.projects) do
    if project == current then index = position; break end
  end
  return M.show(config.projects[(index - 1 + direction) % #config.projects + 1].id)
end

function M.back()
  if previous then return M.show(previous.id) end
  return false
end

function M.move(id, follow)
  local project = project_for(id)
  if not hl.get_active_window() then return false end
  local monitor = hl.get_active_monitor()
  local managed = false
  for _, item in ipairs(M.monitors()) do
    if monitor and monitor.name == item.name then managed = true end
  end
  if not managed then return false end
  busy = true
  local ok, err = pcall(function() o.workspaces.move_window(project.slot, false)() end)
  busy = false
  if not ok then error(err) end
  if follow ~= false then M.show(project.id) end
  return true
end

function M.move_monitor(direction)
  assert(direction == 'l' or direction == 'r' or direction == 'u' or direction == 'd', 'Invalid direction')
  local project, window, target = M.current(), hl.get_active_window(), hl.get_monitor(direction)
  if not project or not window or not target or target.is_mirror then return false end
  local managed = false
  for _, monitor in ipairs(M.monitors()) do
    if monitor.name == target.name then managed = true end
  end
  if not managed then return false end
  local address = 'address:' .. window.address
  M.show(project.id)
  hl.dispatch(hl.dsp.window.move({ window = address,
    workspace = tostring(o.workspaces.workspace_id(target, project.slot)), follow = true }))
  return true
end

-- Function-valued expressions keep Omarchy's keybinding menu functional.
function M.action(method, ...)
  assert(method == 'show' or method == 'commit' or method == 'renderer_ready'
    or method == 'move' or method == 'step' or method == 'back'
    or method == 'move_monitor', 'Invalid action')
  local args = {...}
  local callback = function() return M[method](table.unpack(args)) end
  local encoded = {}
  for _, value in ipairs(args) do
    encoded[#encoded + 1] = type(value) == 'string' and string.format('%q', value) or tostring(value)
  end
  o.bind_expressions[callback] = 'omarchy_projects.action(' .. string.format('%q', method)
    .. (#encoded > 0 and ', ' .. table.concat(encoded, ', ') or '') .. ')'
  return callback
end

function M.bindings()
  for _, project in ipairs(config.projects) do
    local key = 'code:' .. (project.slot + 9)
    o.rebind('SUPER + ' .. key, 'Project: ' .. project.name, M.action('show', project.id))
    o.rebind('SUPER + SHIFT + ' .. key, 'Move window to ' .. project.name, M.action('move', project.id, true))
    o.rebind('SUPER + SHIFT + ALT + ' .. key, 'Send window to ' .. project.name, M.action('move', project.id, false))
  end
  o.rebind('SUPER + TAB', 'Next project', M.action('step', 1))
  o.rebind('SUPER + SHIFT + TAB', 'Previous project', M.action('step', -1))
  o.rebind('SUPER + CTRL + TAB', 'Former project', M.action('back'))
  o.rebind('SUPER + mouse_down', 'Next project', M.action('step', 1))
  o.rebind('SUPER + mouse_up', 'Previous project', M.action('step', -1))
  for key, direction in pairs({ LEFT = 'l', RIGHT = 'r', UP = 'u', DOWN = 'd' }) do
    o.rebind('SUPER + SHIFT + CTRL + ' .. key, 'Move window to ' .. key:lower() .. ' monitor', M.action('move_monitor', direction))
    -- Moving a whole raw workspace would change its project association.
    hl.unbind('SUPER + SHIFT + ALT + ' .. key)
  end
end

function M.setup(settings)
  assert(o and o.workspaces and o.workspaces.slots == 10
    and type(o.workspaces.focus) == 'function'
    and type(o.workspaces.workspace_id) == 'function', 'Omarchy 4.5+ workspace helpers are required')
  config, by_id, by_slot = settings, {}, {}
  busy, settling, selected, previous = false, false, nil, nil
  appearance_project = nil
  if config.preload_wallpapers then renderer_connected = nil else renderer_connected = false end
  renderer_generation = renderer_generation + 1
  published_view = nil
  if config.state_file then
    local file = io.open(config.state_file, 'r')
    if file then published_view = file:read('*a'); file:close() end
  end
  for _, project in ipairs(config.projects) do
    assert(not by_id[project.id] and not by_slot[project.slot], 'Duplicate project id or slot')
    by_id[project.id], by_slot[project.slot] = project, project
  end
  _G.omarchy_projects = M
  if config.workspace_transition then
    hl.animation({ leaf = 'workspaces', enabled = true,
      speed = config.workspace_transition.duration_ms / 100,
      bezier = 'easeOutQuint', style = config.workspace_transition.style })
  end
  if settings.bindings ~= false then M.bindings() end
  local function topology_changed()
    settling = true
    generation = generation + 1
    local pending = generation
    -- Never query/move monitors inside their teardown. Omarchy owns hotplug.
    hl.timer(function()
      if pending ~= generation then return end
      settling = false
      M.publish()
    end, { type = 'oneshot', timeout = 250 })
  end
  hl.on('monitor.added', topology_changed)
  hl.on('monitor.removed', topology_changed)
  hl.on('workspace.active', function()
    if busy or settling then return end
    generation = generation + 1
    local pending = generation
    hl.timer(function()
      if pending ~= generation or settling then return end
      local project = M.current()
      if project then
        local changed = selected ~= project
        if selected and selected ~= project then previous = selected end
        selected = project
        if config.follow_focus and not synchronized(project) then M.show(project.id)
        else
          if renderer_connected and changed then
            hl.dispatch(hl.dsp.global('omarchy-projects:look-' .. project.slot))
          end
          M.request_appearance(project)
        end
      end
    end, { type = 'oneshot', timeout = 40 })
  end)
  selected = M.current()
  if config.history_file and selected then
    local history = io.open(config.history_file, 'r')
    if history then
      local last, former = by_id[history:read('*l')], by_id[history:read('*l')]
      history:close()
      if last == selected then previous = former else previous = last end
    end
  end
  M.publish()
  if config.preload_wallpapers then
    -- Compositor reloads reset Lua while the shell stays alive. Reconnect over
    -- the existing global-shortcut protocol; it has no process or disk work.
    hl.timer(function()
      hl.dispatch(hl.dsp.global('omarchy-projects:connect'))
    end, { type = 'oneshot', timeout = 20 })
    hl.timer(function()
      if renderer_connected == nil then M.renderer_ready(false) end
    end, { type = 'oneshot', timeout = 1000 })
  elseif selected then M.request_appearance(selected) end
  return M
end

return M
