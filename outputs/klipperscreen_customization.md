# IISc Clay Printer — KlipperScreen Customization

## CO2 Concentration Display (PPM) on Titlebar

### How to Re-apply After KlipperScreen Update

If KlipperScreen gets updated/reinstalled, these changes will be lost. Re-apply:

### 1. Edit base_panel.py
`ash
sudo nano /home/pi/KlipperScreen/panels/base_panel.py
`

### 2. Add CO2 to titlebar (around line 265)
Find this block:
`
            for device in devices:
                if n >= nlimit:
                    break
                if device.startswith("extruder") and self.current_extruder is False:
                    self.control["item_box"].add(self.titlebar_labels[f"{device}_eventbox"])
                    n += 1
                elif device.startswith("heater"):
                    self.control["item_box"].add(self.titlebar_labels[f"{device}_eventbox"])
                    n += 1
            for item in self.titlebar_items:
`

Replace with:
`
            for device in devices:
                if n >= nlimit:
                    break
                if device.startswith("extruder") and self.current_extruder is False:
                    self.control["item_box"].add(self.titlebar_labels[f"{device}_eventbox"])
                    n += 1
                elif device.startswith("heater"):
                    self.control["item_box"].add(self.titlebar_labels[f"{device}_eventbox"])
                    n += 1
            for device in devices:
                name = device.split()[1] if len(device.split()) > 1 else device
                if name.lower() == "co2_chamber" and f"{device}_eventbox" in self.titlebar_labels:
                    if self.titlebar_labels[f"{device}_eventbox"].get_parent() is None:
                        self.control["item_box"].add(self.titlebar_labels[f"{device}_eventbox"])
                        n += 1
                        break
            for item in self.titlebar_items:
`

### 3. Change unit from ° to PPM
Find:
`
self.titlebar_labels[device].set_label(f"{name}{temp:.0f}°")
`

Replace with:
`
self.titlebar_labels[device].set_label(f"{name}{temp:.0f}{' PPM' if 'co2' in device.lower() else '°'}")
`

### 4. Restart
`ash
sudo systemctl restart KlipperScreen
`

---

## Temperature UI Removal

### temperature.py modifications
`ash
sudo nano /home/pi/KlipperScreen/panels/temperature.py
`
- Line: title = title or _("Temperature") → title = title or _("CO2")
- Line: Temp (°C) → CO2 (ppm)

### KlipperScreen.conf (already set)
`ini
[printer Printer]
hidden_sensors: extruder, extruder1

[menu __main temperature]
enable: False
`

---

## Key Files Modified
| File | Changes |
|------|---------|
| /home/pi/KlipperScreen/panels/base_panel.py | CO2 in titlebar, PPM unit |
| /home/pi/KlipperScreen/panels/temperature.py | CO2 labels, ppm headers |
| /home/pi/printer_data/config/KlipperScreen.conf | hidden_sensors, menu disable |
