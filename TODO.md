# TODO — nx

## ما تم بناؤه ✓

- `src/models/package.py` — Package dataclass
- `src/api/stable.py` — البحث في nixpkgs stable
- `src/api/unstable.py` — البحث في nixpkgs unstable
- `src/api/flakes.py` — استخراج حزم الـ flakes عبر `nix flake show --json`
- `src/core/manager.py` — البحث في المصادر بالتتابع مع generator
- `src/core/config.py` — قراءة وكتابة `~/.config/nx/config.toml`
- `src/core/writer.py` — تعديل `configuration.nix` (جزئي)
- `src/ui/display.py` — واجهة curses كاملة مع pagination
- `src/ui/first_setup.py` — صفحات السيتاب (جزئي)
- `main.py` — argparse مع install/remove/upgrade (جزئي)
- `pyproject.toml` — إعداد المشروع والـ dependencies

---

## ما لم يكتمل بعد

### ١. src/ui/first_setup.py

- ربط نتيجة `_setup` بـ `config.py` عبر `save_config`

### ٢. src/core/writer.py

**الحالة 1 — بدون flakes:**

- `add_package` ✓ موجود
- `remove_package` ✓ موجود

**الحالة 2 — مع flakes:**

- `add_flake` في `flake.nix` ✗
- `remove_flake` في `flake.nix` ✗

**الحالة 3 — مع flakes + home-manager:**

- `add_home_package` في `home.nix` ✗ (حالتان فقط: with_pkgs و explicit_pkgs)
- `remove_home_package` في `home.nix` ✗
- `add_flake` في `flake.nix` ✗
- `remove_flake` في `flake.nix` ✗

**الحالة 4 — مع flakes + nx-flakes.nix:**

- `add_flake` في `nx-flakes.nix` ✗
- `remove_flake` في `nx-flakes.nix` ✗

### ٣. main.py

- قراءة `config.toml` عند كل تشغيل
- تشغيل `first_setup` إن لم يوجد `config.toml`
- تمرير الـ mode لكل handle function
- `handle_upgrade` ✗
- `handle_flakes` ✗ (هيكل فقط)
- الحالة 3 — سؤال المستخدم: نظام أم مستخدم؟

---

## مستقبلي — ما بعد v1.0

- `nx --upgrade` — تحديث الأداة نفسها
- `nx --uninstall` — إزالة الأداة
- `man nx` — صفحة الدليل
- تعليقات `# nx-start` / `# nx-end` في ملفات النظام
- دعم `programs.*` كـ install_type
- كشف تعدد `systemPackages` في نفس الملف
- activation script للـ nix eval-cache

## أمان — قبل الإطلاق ⚠️

- **بيانات اعتماد NixOS Search** — استبدال Base64 في `stable.py` و`unstable.py` بمتغير بيئة
- **التحقق من أسماء الحزم** — إضافة `validate_package_name()` قبل أي كتابة في الملفات
- **فحص الصلاحيات** — التحقق من وجود `sudo` قبل الكتابة في `/etc/nixos/` مع رسالة واضحة
