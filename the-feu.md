# TODO — nx (nix-install)

## ما تم بناؤه
- `src/models/package.py` — Package dataclass
- `src/api/stable.py` — البحث في nixpkgs stable
- `src/api/unstable.py` — البحث في nixpkgs unstable
- `src/api/flakes.py` — استخراج حزم الـ flakes عبر `nix flake show --json`
- `src/core/manager.py` — يجمع النتائج من المصادر

---

## ما لم يُبنَ بعد

### ١. تعديل Package dataclass
- إضافة حقل `install_type: str` — قيمته `"package"` أو `"program"`
- هذا يحدد كيف تُكتب الحزمة في ملفات النظام

### ٢. تعديل stable.py و unstable.py
- البحث في **options** أيضاً بجانب packages
- استخراج `install_type` لكل حزمة:
  - `"package"` → تُضاف في `environment.systemPackages`
  - `"program"` → تُضاف كـ `programs.x.enable = true`

### ٣. src/core/writer.py
أهم وأعقد ملف في المشروع — يتعامل مع تعديل ملفات النظام.

**عند الإضافة في `configuration.nix`:**
يتعامل مع كل أشكال كتابة `environment.systemPackages`:
- `with pkgs; [ vim git ]` ← الأكثر شيوعاً
- `[ pkgs.vim pkgs.git ]` ← بدون with
- `with pkgs; [ vim ] ++ with pkgs; [ git ]` ← دمج قوائم
- `import ./packages.nix { inherit pkgs; }` ← ملف خارجي
- `with pkgs; [ vim ] ++ import ./packages.nix` ← دمج مع خارجي

**عند الإضافة كـ program:**
```nix
programs.steam.enable = true;
```

**في `nix-install-flakes.nix`:**
- الملف موجود وفيه حزم → يضيف
- الملف فارغ → ينشئ الهيكل ويضيف
- الملف غير موجود → ينشئه من الصفر

**عند الحذف:**
- الحزمة موجودة → يحذفها
- الحزمة غير موجودة → يخبر المستخدم
- الحزمة الأخيرة في الملف → يسأل المستخدم

**الأمان:**
- نسخة احتياطية قبل أي تعديل
- التراجع التلقائي إن فشل `nixos-rebuild`

### ٤. src/ui/display.py
- عرض نتائج البحث بـ pagination (17 حزمة لكل صفحة)
- جدول: `#  Name  Version  Description`
- التنقل: `(n) next  (p) prev  (q) done`
- اختيار متعدد: `1,3,5`
- عرض ملخص قبل التثبيت

### ٥. main.py النهائي
استقبال الأوامر عبر `argparse`:

```
sudo nx install [pkg]          — تثبيت حزمة
sudo nx remove [pkg]           — حذف حزمة
sudo nx upgrade                — nixos-rebuild switch
sudo nx upgrade --flakes       — nix flake update + rebuild
sudo nx flakes [flake_url]     — البحث في flake محدد وتثبيت
sudo nx flakes remove [pkg]    — حذف flake من القائمة
nx --help                      — المساعدة
nx --upgrade                   — تحديث الأداة نفسها
nx --uninstall                 — إزالة الأداة
man nx                         — الدليل الكامل
```

### ٦. إعداد أول تشغيل
عند أول `nx install` تسأل الأداة:
```
[1] ملف واحد — nix-install.nix (packages + flakes)
[2] ملف للflakes فقط + packages في configuration.nix
[3] ملف للpackages فقط + flakes في flake.nix
[4] لا ملفات إضافية — كل شيء في ملفاته الأصلية
```
تحفظ الاختيار في `~/.config/nx/config.toml`

### ٧. activation script في NixOS
يشغّل عند كل `nixos-rebuild switch` — يُدفئ الـ nix eval-cache للـ flakes:
```nix
system.activationScripts.nx-cache = ''
  python /path/to/nx/cache_update.py
'';
```
تضيفه الأداة عند التثبيت وتحذفه عند `nx --uninstall`

### ٨. man page
صفحة دليل رسمية لـ `man nx`

---

## ملفات الاختبار
```
/etc/nixos-test/
├── configuration.nix
├── flake.nix
├── nix-install-packages.nix
└── nix-install-flakes.nix
```
البرنامج يعدّل هذه بدل ملفات النظام الحقيقية أثناء التطوير.