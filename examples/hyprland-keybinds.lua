-- hyprwhispr — hold-to-talk binding for Hyprland (Lua config, e.g. KoolDots)
--
-- For users whose Hyprland config is written in Lua. `hl.bind` registers a
-- press bind; the `release = true` option registers the release bind. Add this
-- to your user keybinds file (for KoolDots:
-- ~/.config/hypr/UserConfigs/user_keybinds.lua) and run `hyprctl reload`.

hl.bind("SUPER + V", hl.dsp.exec_cmd("hyprwhispr record-start"), {
  description = "hyprwhispr: hold to talk",
})
hl.bind("SUPER + V", hl.dsp.exec_cmd("hyprwhispr record-stop"), {
  description = "hyprwhispr: release to send",
  release = true,
})
