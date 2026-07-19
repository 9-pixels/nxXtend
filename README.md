# nix-install

أداة CLI تفاعلية للبحث عن حزم Nix وتثبيتها من مصادر متعددة.

## الفكرة

`nix search` يبحث في مصدر واحد فقط. `nix-install` يبحث في stable وunstable والـ flakes المشهورة دفعة واحدة، ويعرض النتائج بشكل واضح، ويكتب الحزم في ملفات النظام الصحيحة تلقائياً ثم يشغل `nixos-rebuild`.

## الاستخدام

```bash
nix-install steam
```

```
searching in stable...     ✓ (23)
searching in unstable...   ✓ (31)
searching in flakes...     ✓ (4)

  [1] Stable packages    (23)
  [2] Unstable packages  (31)
  [3] Flakes             (4)

  [0] Cancel

Choose source: 2

  #   Name          Version     Description
  ──────────────────────────────────────────
  1   steam         1.0.0.79    Valve's game platform
  2   steam-run     1.0.0.79    Run non-NixOS binaries via FHS
  ...

Select (1-31): 1,2

  ✓ تمت إضافة steam لـ configuration.nix
  ✓ تمت إضافة steam-run لـ configuration.nix

  running nixos-rebuild switch...
  building the system configuration...
  ✓ Done.
```

### رابط مخصص

```bash
nix-install github:caelestia-dots/shell
```

```
searching in flakes...     ✓ (6)

  #   Name                Version    Description
  ──────────────────────────────────────────────
  1   caelestia-shell     2.1.0      Hyprland shell suite
  ...

Select (1-6): 1

  ✓ سطر الاستيراد موجود في flake.nix
  ✓ تمت إضافة caelestia-shell لـ nix-install-flakes.nix

  running nixos-rebuild switch...
  ✓ Done.
```

## المصادر

| المصدر | الوصف |
|--------|-------|
| nixpkgs stable | المستودع الرسمي — الإصدار المستقر |
| nixpkgs unstable | المستودع الرسمي — آخر الإصدارات |
| flakes | قائمة flakes مشهورة محددة مسبقاً + روابط مخصصة |

### الـ Flakes المدعومة

- `home-manager` — إدارة بيئة المستخدم
- `hyprland` — Wayland compositor
- `chaotic-nyx` — حزم غير رسمية
- `nur` — NixOS User Repository
- `nixos-hardware` — إعدادات الأجهزة
- `devenv` — بيئات تطوير معزولة
- `fenix` — Rust toolchains
- `nix-alien` — تشغيل binaries خارج NixOS
- `niri`, `ags`, `astal` — بيئات رسومية
- وغيرها

## إدارة الملفات

عند أول تشغيل تسأل الأداة كيف تريد إدارة ملفاتك:

```
[1] ملف واحد — nix-install.nix
    فيه env packages والflakes معاً
    → configuration.nix يستورده بسطر واحد

[2] ملفان منفصلان
    → nix-install-flakes.nix  فيه الflakes فقط
    → env packages تُكتب في configuration.nix مباشرة

[3] ملفان منفصلان
    → nix-install-packages.nix  فيه env packages فقط
    → flakes تُكتب في flake.nix مباشرة

[4] لا ملفات إضافية
    → env packages تُكتب في configuration.nix مباشرة
    → flakes تُكتب في flake.nix مباشرة
```

### التثبيت حسب المصدر

**stable / unstable:**
1. يبحث عن `environment.systemPackages` في الملف المحدد
2. يضيف الحزمة
3. يشغل `nixos-rebuild switch`

**flakes:**
1. يتحقق من وجود سطر الاستيراد في `flake.nix` — يضيفه إن لم يوجد
2. يضيف الحزمة في الملف المحدد
3. يشغل `nixos-rebuild switch`

### الحالات المعالجة في configuration.nix

- `environment.systemPackages` موجودة وفيها حزم → يضيف بعدها
- `environment.systemPackages` موجودة لكن فارغة → يضيف داخلها
- `environment.systemPackages` غير موجودة → ينشئها

## التقنيات

| التقنية | الاستخدام |
|---------|-----------|
| Python | لغة البرنامج |
| requests | طلبات HTTP للبحث في nixos.org API |
| rich | عرض النتائج في الـ terminal |
| nix flake show --json | استخراج حزم الـ flakes |
| subprocess | تنفيذ nixos-rebuild وعرض output مباشرة |

## هيكل المشروع

```
nix-install/
├── main.py
└── src/
    ├── api/
    │   ├── stable.py      — البحث في nixpkgs stable عبر nixos.org API
    │   ├── unstable.py    — البحث في nixpkgs unstable عبر nixos.org API
    │   └── flakes.py      — البحث في الflakes عبر nix flake show --json
    ├── models/
    │   └── package.py     — Package dataclass
    ├── core/
    │   └── manager.py     — يربط الجميع ويدير التدفق
    └── ui/
        └── display.py     — العرض عبر rich
```

## القرارات التصميمية

- **لا GitHub API** — الـ flakes محددة مسبقاً أو يدخلها المستخدم مباشرة
- **لا async** — طلبات متتابعة: stable ثم unstable ثم flakes مع عرض تقدم لكل مصدر
- **لا TUI** — CLI بسيط، pagination يدوي (17 حزمة لكل صفحة)
- **subprocess بدون PIPE** — output التثبيت يظهر مباشرة للمستخدم
- **ملف إعداد الأداة** — خيار عند أول تشغيل، لا لمس لملفات النظام بشكل أعمى