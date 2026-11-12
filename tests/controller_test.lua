local failures, passes = 0, 0
local events, timers, monitors, windows, focused, active, calls, bases, tearing

local function equal(actual, expected)
  assert(actual == expected, 'expected ' .. tostring(expected) .. ', got ' .. tostring(actual))
end

local function flush()
  local pending = timers
  timers = {}
  for _, timer in ipairs(pending) do timer() end
end

local function fixture(options)
  events, timers, calls, windows, bases, tearing = {}, {}, {}, {}, { left = 0, right = 40 }, false
  monitors = {
    { name = 'left', description = 'Left Display', id = 0, active_workspace = { id = 1 } },
    { name = 'right', description = 'Right Display', id = 1, active_workspace = { id = 41 } },
  }
  focused = monitors[2]
  local function find(name)
    for _, monitor in ipairs(monitors) do
      if monitor.name == name or 'desc:' .. monitor.description == name then return monitor end
    end
  end
  local function emit(event, ...)
    for _, callback in ipairs(events[event] or {}) do callback(...) end
  end
  local function show(slot, name)
    assert(not tearing, 'monitor accessed during teardown')
    local monitor = assert(find(name))
    focused = monitor
    monitor.active_workspace = { id = bases[name] + slot }
    calls[#calls + 1] = { slot = slot, name = name }
    emit('workspace.active', monitor.active_workspace)
  end
  hl = {
    get_monitors = function() return monitors end,
    get_monitor = function(name)
      if name == 'l' then return monitors[1] end
      if name == 'r' then return monitors[2] end
      return find(name)
    end,
    get_active_monitor = function() return focused end,
    get_active_window = function() return active end,
    on = function(event, callback)
      events[event] = events[event] or {}
      table.insert(events[event], callback)
    end,
    timer = function(callback) timers[#timers + 1] = callback end,
    unbind = function() end,
    dsp = {
      focus = function(options) return { kind = 'focus', options = options } end,
      window = { move = function(options) return { kind = 'move', options = options } end },
    },
    dispatch = function(dispatch)
      if dispatch.kind == 'focus' then focused = assert(find(dispatch.options.monitor)) end
      if dispatch.kind == 'move' then
        local target = tonumber(dispatch.options.workspace)
        active.workspace = target
        for _, monitor in ipairs(monitors) do
          if target > bases[monitor.name] and target <= bases[monitor.name] + 10 then
            active.monitor = monitor.name
            if dispatch.options.follow then focused = monitor end
          end
        end
      end
    end,
  }
  o = {
    bind_expressions = {},
    rebind = function(keys, description, action)
      calls[#calls + 1] = { keys = keys, description = description, action = action }
    end,
    workspaces = {
      slots = 10,
      workspace_id = function(monitor, slot)
        assert(not tearing, 'workspace helper queried during teardown')
        return bases[monitor.name] + slot
      end,
      focus = function(slot, name) return function() show(slot, name) end end,
      move_window = function(slot, follow) return function()
        active.workspace = bases[focused.name] + slot
        if follow then show(slot, focused.name) end
      end end,
    },
  }
  active = { address = '0x123', monitor = 'right', workspace = 41 }
  local config = {
    projects = {
      { id = 'atlas', name = 'Atlas', slot = 1 },
      { id = 'boreal', name = 'Boreal', slot = 3 },
      { id = 'personal', name = 'Personal', slot = 7 },
    },
    monitors = {}, follow_focus = true, bindings = false,
  }
  for key, value in pairs(options or {}) do config[key] = value end
  local controller = dofile('hypr/controller.lua').setup(config)
  return controller, emit, config
end

local function test(name, callback)
  local ok, err = pcall(callback)
  if ok then passes = passes + 1; print('PASS ' .. name)
  else failures = failures + 1; print('FAIL ' .. name .. ': ' .. err) end
end

test('switch uses saved mappings and preserves the focused screen', function()
  local controller = fixture()
  controller.show('boreal')
  equal(monitors[1].active_workspace.id, 3)
  equal(monitors[2].active_workspace.id, 43)
  equal(focused.name, 'right')
  equal(controller.current().id, 'boreal')
end)

test('rapid switches cannot leave mismatched projects', function()
  local controller = fixture()
  for index = 1, 100 do controller.show(index % 2 == 0 and 'personal' or 'boreal') end
  flush()
  equal(monitors[1].active_workspace.id, 7)
  equal(monitors[2].active_workspace.id, 47)
end)

test('follow and silent moves retain the physical monitor', function()
  local controller = fixture()
  controller.move('boreal', true)
  equal(active.workspace, 43)
  equal(active.monitor, 'right')
  equal(monitors[1].active_workspace.id, 3)
  controller.move('personal', false)
  flush()
  equal(active.workspace, 47)
  equal(monitors[1].active_workspace.id, 3)
  equal(monitors[2].active_workspace.id, 43)
end)

test('cross-screen move stays inside the project', function()
  local controller = fixture()
  controller.move_monitor('l')
  equal(active.monitor, 'left')
  equal(active.workspace, 1)
  equal(focused.name, 'left')
  equal(monitors[2].active_workspace.id, 41)
end)

test('cycling follows config order and back toggles projects', function()
  local controller = fixture()
  controller.step(1)
  equal(controller.current().id, 'boreal')
  controller.step(1)
  equal(controller.current().id, 'personal')
  controller.step(1)
  equal(controller.current().id, 'atlas')
  controller.back()
  equal(controller.current().id, 'personal')
  controller.back()
  equal(controller.current().id, 'atlas')
end)

test('external workspace focus synchronizes once and ignores unconfigured slots', function()
  local controller, emit = fixture()
  monitors[2].active_workspace = { id = 43 }
  emit('workspace.active', monitors[2].active_workspace)
  flush()
  equal(monitors[1].active_workspace.id, 3)
  monitors[2].active_workspace = { id = 50 }
  emit('workspace.active', monitors[2].active_workspace)
  flush()
  equal(monitors[1].active_workspace.id, 3)
end)

test('hotplug never accesses a monitor during teardown', function()
  local controller, emit = fixture({ state_file = os.tmpname() })
  tearing = true
  emit('monitor.removed', monitors[2])
  emit('workspace.active', { id = 3 })
  equal(#calls, 0)
  tearing = false
  table.remove(monitors, 2)
  focused = monitors[1]
  flush()
  controller.show('boreal')
  equal(monitors[1].active_workspace.id, 3)
end)

test('former project follows externally focused windows too', function()
  local controller, emit = fixture()
  monitors[2].active_workspace = { id = 43 }
  emit('workspace.active', monitors[2].active_workspace)
  flush()
  controller.back()
  equal(controller.current().id, 'atlas')
end)

test('mirrors are excluded and monitor selectors are respected', function()
  local controller = fixture({ monitors = { 'desc:Left Display' } })
  controller.show('boreal')
  equal(monitors[1].active_workspace.id, 3)
  equal(monitors[2].active_workspace.id, 41)
  equal(focused.name, 'right')
  controller = fixture()
  monitors[1].is_mirror = true
  equal(#controller.monitors(), 1)
end)

test('no monitors, no window, and unknown projects cause no moves', function()
  local controller = fixture()
  local ok = pcall(controller.show, 'missing')
  equal(ok, false)
  equal(#calls, 0)
  active = nil
  equal(controller.move('boreal'), false)
  monitors = {}
  equal(controller.show('boreal'), false)
end)

test('mapping is read again instead of cached by connector', function()
  local controller = fixture()
  bases.right = 80
  controller.show('personal')
  equal(monitors[2].active_workspace.id, 87)
end)

test('keybinding menu expressions return runnable callbacks', function()
  local controller = fixture({ bindings = true })
  local binding
  for _, item in ipairs(calls) do if item.keys == 'SUPER + code:12' then binding = item end end
  assert(binding)
  local expression = assert(o.bind_expressions[binding.action])
  local callback = assert(load('return ' .. expression))()
  callback()
  equal(controller.current().id, 'boreal')
end)

test('published names round trip as JSON data, including markup', function()
  local file = os.tmpname()
  local controller, _, config = fixture({ state_file = file })
  config.projects[1].name = 'München " <img src="https://invalid.test/x">'
  controller.publish()
  local stream = assert(io.open(file))
  local output = stream:read('*a')
  stream:close()
  assert(output:find('\\"', 1, true))
  assert(output:find('"boreal":43', 1, true))
  os.remove(file)
end)

print(string.format('%d passed, %d failed', passes, failures))
os.exit(failures > 0 and 1 or 0)
