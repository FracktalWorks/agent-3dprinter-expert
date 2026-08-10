; ============================================================
; Circle Test Pattern ? Toolhead only, Z=0, no extrusion
; Build: 200x200mm, Home: (0,0) top-left
; ============================================================

G90                          ; Absolute positioning
G21                          ; Units: mm
G1 Z0 F300                   ; Ensure Z at 0
M117 Circling at Z=0

; Move to center of bed
G1 X100 Y100 F3000

; --- Concentric circles, increasing radius ---
; Radius 10mm
G1 X110 Y100 F1500           ; Move to start of circle
G3 X110 Y100 I-10 J0 F800    ; CCW circle r=10
G1 X100 Y100 F1500           ; Back to center

; Radius 20mm
G1 X120 Y100 F1500
G3 X120 Y100 I-20 J0 F800
G1 X100 Y100 F1500

; Radius 30mm
G1 X130 Y100 F1500
G3 X130 Y100 I-30 J0 F800
G1 X100 Y100 F1500

; Radius 40mm
G1 X140 Y100 F1500
G3 X140 Y100 I-40 J0 F800
G1 X100 Y100 F1500

; Radius 50mm
G1 X150 Y100 F1500
G3 X150 Y100 I-50 J0 F800
G1 X100 Y100 F1500

; Radius 60mm
G1 X160 Y100 F1500
G3 X160 Y100 I-60 J0 F800
G1 X100 Y100 F1500

; Radius 70mm
G1 X170 Y100 F1500
G3 X170 Y100 I-70 J0 F800
G1 X100 Y100 F1500

; Radius 80mm
G1 X180 Y100 F1500
G3 X180 Y100 I-80 J0 F800
G1 X100 Y100 F1500

; --- Spiral (continuous widening circle) ---
G1 X100 Y100 F3000
G1 X105 Y100 F1500
G2 X105 Y100 I-5 J0 F600      ; r=5
G2 X112 Y100 I-12 J0 F600     ; r=12
G2 X122 Y100 I-22 J0 F600     ; r=22
G2 X135 Y100 I-35 J0 F600     ; r=35
G2 X150 Y100 I-50 J0 F600     ; r=50
G2 X168 Y100 I-68 J0 F600     ; r=68
G2 X188 Y100 I-88 J0 F600     ; r=88

; --- Done ---
G1 X100 Y100 F3000            ; Back to center
M117 Circles complete
