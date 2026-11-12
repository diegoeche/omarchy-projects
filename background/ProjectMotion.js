// Pure preparation/math: no filesystem or image work on the animation path.
function channels(value) {
  var text = String(value || "")
  if (/^#[0-9a-fA-F]{8}$/.test(text)) text = "#" + text.slice(3)
  if (!/^#[0-9a-fA-F]{6}$/.test(text)) return null
  return [parseInt(text.slice(1, 3), 16), parseInt(text.slice(3, 5), 16), parseInt(text.slice(5, 7), 16)]
}

function hex(values) {
  return "#" + values.map(function(value) {
    var result = Math.max(0, Math.min(255, Math.round(value))).toString(16)
    return result.length === 1 ? "0" + result : result
  }).join("")
}

function mix(pair, progress) {
  return hex(pair[0].map(function(value, index) { return value + (pair[1][index] - value) * progress }))
}

function parseBase(raw, fallback) {
  var values = {}
  String(raw || "").split("\n").forEach(function(line) {
    var match = line.match(/^\s*([\w-]+)\s*=\s*["']?(#[0-9a-fA-F]{6})/)
    if (match) values[match[1]] = match[2]
  })
  values.foreground = values.foreground || values.color7 || fallback.foreground
  values.background = values.background || values.color0 || fallback.background
  values.accent = values.accent || values.color4 || fallback.accent
  values.urgent = values.red || values.color1 || fallback.urgent
  values.muted = values.muted || values.color8 || values.foreground
  return values
}

function validManifest(data) {
  if (!data || data.version !== 1 || !Array.isArray(data.assets) || data.assets.length > 10
      || !Array.isArray(data.projects) || data.projects.length > 10
      || ["slide", "slidevert", "fade"].indexOf(data.style) < 0
      || !Number.isInteger(data.duration) || data.duration < 80 || data.duration > 300) return false
  var keys = {}, ids = {}, slots = {}
  for (var i = 0; i < data.assets.length; i++) {
    var row = data.assets[i]
    if (!row || !/^[a-f0-9]{64}$/.test(row.key) || keys[row.key]
        || typeof row.path !== "string" || row.path[0] !== "/" || row.path.length > 4096
        || /[\u0000-\u001f]/.test(row.path)
        || !Number.isInteger(row.width) || row.width < 0 || row.width > 65536
        || !Number.isInteger(row.height) || row.height < 0 || row.height > 65536) return false
    keys[row.key] = true
  }
  for (var j = 0; j < data.projects.length; j++) {
    var project = data.projects[j]
    if (!project || !/^[a-z][a-z0-9_-]{0,39}$/.test(project.id) || ids[project.id]
        || !Number.isInteger(project.slot) || project.slot < 1 || project.slot > 10 || slots[project.slot]
        || (project.asset !== "" && !keys[project.asset])
        || typeof project.colors !== "string" || project.colors.length > 262144
        || typeof project.shell !== "string" || project.shell.length > 262144) return false
    ids[project.id] = slots[project.slot] = true
  }
  return true
}

function resolved(value, base, shell) {
  var text = String(value || "").trim().split(/\s+/)[0]
  for (var i = 0; i < 8 && !channels(text); i++) {
    var next = base[text] || shell[text]
    if (!next || next === text) break
    text = String(next).trim().split(/\s+/)[0]
  }
  return channels(text)
}

function palettePlan(sourceBase, sourceShell, targetBase, targetShell) {
  var base = {}, shell = {}
  ;["foreground", "background", "accent", "urgent", "muted"].forEach(function(key) {
    var from = channels(sourceBase[key]), to = channels(targetBase[key])
    if (from && to) base[key] = [from, to]
  })
  var keys = Object.keys(Object.assign({}, sourceShell, targetShell))
  keys.forEach(function(key) {
    var from = resolved(sourceShell[key], sourceBase, sourceShell)
    var to = resolved(targetShell[key], targetBase, targetShell)
    if (from && to) shell[key] = [from, to]
  })
  return { base: base, shell: shell, fromShell: sourceShell, toShell: targetShell }
}

function paletteFrame(plan, progress) {
  var base = {}, shell = Object.assign({}, progress < 1 ? plan.fromShell : plan.toShell)
  Object.keys(plan.base).forEach(function(key) { base[key] = mix(plan.base[key], progress) })
  Object.keys(plan.shell).forEach(function(key) { shell[key] = mix(plan.shell[key], progress) })
  return { base: base, shell: shell }
}

function offset(key, from, to, direction, progress, extent) {
  if (from === to) return 0
  if (key === from) return -direction * progress * extent
  if (key === to) return direction * (1 - progress) * extent
  return 0
}
