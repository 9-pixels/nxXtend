# 📋 قائمة المشاكل والتحسينات — `nx` (nix-install)

> **حالة المشروع:** في مرحلة التطوير الأولية (لم يكتمل بعد)
> **الهدف الأصلي:** أداة CLI باسم `nx` تبحث عن حزم Nix وتثبتها تفاعلياً.
> **الرؤية النهائية:** أداة CLI تدعى `nx` تدعم `install`/`remove`/`upgrade`/`flakes`/`upgrade --flakes`
> **التواصل الرسمي:** انظر `project-status.md` في جذر المشروع.

---

## فهرس المحتويات

1. [الخلفية ورؤية المشروع](#الخلفية-ورؤية-المشروع)
2. [مشاكل الأمن](#مشاكل-الأمن--أولوية-عالية)
3. [البنية والتصميم](#البنية-والتصميم--أولوية-متوسطة)
4. [معالجة الأخطاء](#معالجة-الأخطاء--أولوية-متوسطة)
5. [تجربة المستخدم](#تجربة-المستخدم--أولوية-منخفضة-متوسطة)
6. [الصيانة والجودة](#الصيانة-والجودة--أولوية-منخفضة)
7. [مكانيزمات لم تُنفّذ بعد](#مكانيزمات-لم-تُنفّذ-بعد)
8. [اقتراحات تحسين في وقت التطوير](#اقتراحات-تحسين-في-وقت-التطوير)
9. [خارطة طريق للإصدار 1.0](#خارطة-طريق-للإصدار-10)

---

## الخلفية ورؤية المشروع

**المشكلة الأصلية:** `nix search` يبحث في مصدر واحد فقط، وتثبيت الحزمة يتطلب تعديل يدوي في `configuration.nix`.

**الحل المقترح:** أداة `nx` تبحث في مصادر متعددة (stable، unstable، flakes) وتكتب في الملفات تلقائياً.

**الأوامر النهائية المخططة:**
```
sudo nx install [pkg]          → تثبيت من stable/unstable
sudo nx remove [pkg]           → إزالة حزمة
sudo nx upgrade                → nixos-rebuild switch
sudo nx upgrade --flakes       → nix flake update + rebuild
sudo nx flakes [flake_url]     → البحث وتثبيت من flake
sudo nx flakes remove [pkg]    → إزالة flake من القائمة
nx --help                      → المساعدة
nx --upgrade                   → تحديث الأداة نفسها
nx --uninstall                 → إزالة الأداة
man nx                         → الدليل الكامل
```

**القرارات التصميمية الأصلية (موثقة في `project-status.md`):**
- ✅ Python — مرونة مع Nix APIs
- ✅ تسلسلية (لا async) — البساطة والاستقرار
- ✅ CLI بسيط مع `rich` (لا curses، لا textual)
- ✅ البحث بالتتابع: stable → unstable → flakes مع عرض تقدم
- ✅ Flakes تُدخل يدوياً كرابط (لا GitHub API مجاني)

---

## مشاكل الأمن ⚠️ أولوية عالية

### 1. بيانات اعتماد NixOS Search مُشفّرة بـ Base64 في الكود

**المكان:** `src/api/stable.py`، `src/api/unstable.py`

**المشكلة:**
```python
"Authorization": "Basic YVdWU0FMWHBadjpYOGdQSG56TDUyd0ZFZWt1eHNmUTljU2g="
```

**لماذا هذه مشكلة؟**
- Base64 **ليس تشفيرًا** — قابل للعكس في لحظة بـ `base64 -d`.
- هذه البيانات اعتماد حقيقية مستخرجة من Developer Tools. إنها:
  - **تاريخيًا** — قد تكون منتهاة الآن.
  - **عامة** — NixOS تستخدمها للبحث العام، لكنها قد تتغير.
  - **مُرفقة** — أي نسخة git قديمة تحتاجها شخص آخر.
- ينتهك مبدأ أمان "السرية لا تُدخل في الكود".

**الحل المقترح (مرحلة 1):**
1. **استخراجه إلى متغيّر بيئة:**
   ```python
   import os
   API_TOKEN = os.environ.get("NIXOS_SEARCH_TOKEN", "")
   HEADERS = {
       "Content-Type": "application/json",
   }
   if API_TOKEN:
       HEADERS["Authorization"] = f"Basic {API_TOKEN}"
   ```
2. **إنشاء `.env.example`:**
   ```env
   # احصل على التوكن من: browser DevTools → Network → POST request → Authorization header
   NIXOS_SEARCH_TOKEN=
   ```
3. **توثيق التدوير:** أضف توجيه إلى `project-status.md` أن هذا التوكن يجب تدويره على NixOS.

> **ملاحظة:** إن كانت هذه البيانات لا زالت فعالة، فهي الآن معرضة. المشروع مفتوح المصدر على GitHub، لذا أي شخص يمكنه فكها.

### 2. لا يوجد تحقق من صحة أسماء الحزم (حقن Nix)

**المكان:** `src/core/writer.py` — جميع دوال `add_package_*`

**المشكلة:**
```nix
environment.systemPackages = with pkgs; [
hello
];  # ← المستخدم يدخل "}; evil_command #"
```

**لماذا هذه مشكلة؟**
- `configuration.nix` يُنفَّذ ككود Nix كامل أثناء `nixos-rebuild` — ليس مجرد نص.
- أسماء الحزم المنقرصة من المدخل غير المُتحقّق يمكن أن تحبط البنية النحوية أو تنفذ أوامر غير مقصودة.

**الحل المقترح:**
1. **توحيد أسماء الحزم بـ regex آمن:**
   ```python
   import re
   
   def validate_package_name(name: str) -> bool:
       """أسماء الحزم تتطلب: [a-zA-Z0-9_-.+] فقط"""
       return bool(re.match(r'^[a-zA-Z0-9_.+-]+$', name))
   ```
2. **رفض قبل أي كتابة:**
   ```python
   if not validate_package_name(pkg_name):
       console.print(f"[red]اسم الحزمة غير صالح: {pkg_name}[/red]")
       return content, False
   ```

### 3. كتابة مباشرة في `/etc/nixos/` بدون فحص صلاحيات

**المكان:** `src/core/writer.py` — `CONFIG_PATH`

**المشكلة:** الكود يكتب في `/etc/nixos-test/` (للتطوير)، لكن الهدف النهائي هو `/etc/nixos/` الذي يتطلب `sudo`.

**الحل المقترح:**
- جعل المسار قابلًا للتكوين عبر `--config` أو `NIX_CONFIG_PATH`.
- فحص الصلاحيات قبل الكتابة مع رسالة واضحة إذا احتياج `sudo`.

---

## البنية والتصميم ⚠️ أولوية متوسطة

### 4. `main.py` نص اختبار — لا يوجد نقطة دخول حقيقية

**المكان:** `main.py`

**المشكلة:**
```python
config = Path("/etc/nixos-test/configuration.nix")
content = config.read_text()
new_content, found = remove_package(content, "flatpak", config.parent)
```
- مسار وحزمة مكعبتان — لا يمكن تغييرهما.
- لا يوجد `argparse`، لا أوامر `nx`، لا تكامل.
- الدالة `show_results()` في `display.py` غير مستدعاة أبدًا.

**الحل المقترح — بناء `main.py` النهائي خطوة بخطوة:**

**الخطوة 1: `argparse` الأساسي**
```python
import argparse

parser = argparse.ArgumentParser(
    prog="nx",
    description="NixOS Package Manager — ابحث، ثبت، وأزل حزم Nix تفاعلياً"
)
subparsers = parser.add_subparsers(dest="command", required=True)

# nx install [pkg]
install_p = subparsers.add_parser("install", help="ثبت حزمة من stable/unstable")
install_p.add_argument("name", type=str, help="اسم الحزمة")
install_p.add_argument("--config", type=str, default="/etc/nixos/configuration.nix")

# nx remove [pkg]
remove_p = subparsers.add_parser("remove", help="أزل حزمة")
remove_p.add_argument("name", type=str)
remove_p.add_argument("--config", type=str, default="/etc/nixos/configuration.nix")

# nx search [query] — خطوة مستقبلية
# ...
```

### 5. عدم وجود تكامل بين الوحدات

**المشكلة:** `display.py`، `manager.py`، `writer.py` — كل واحدة عاملة بعزل.

**التكامل المطلوب:**
```
nx install firefox
    ↓
manager.search("firefox")  ← بحث في stable + unstable + flakes
    ↓
display.show_results(results)  ← عرض جدول تفاعلي
    ↓
مستخدم يختار رقم الحزمة (مثلاً 3)
    ↓
writer.add_package(content, "firefox", config_dir)  ← تعديل configuration.nix
    ↓
writer.backup_config()  ← نسخة احتياطية قبل الكتابة
    ↓
console.print("تم التثبيت — شغّل sudo nixos-rebuild switch")
```

### 6. دمج وإزالة تكرار الحزم بين المصادر

**المكان:** `src/core/manager.py`

**المشكلة الحالية:**
```python
def search(pkg_name: str):
    stable_results = deduplicate(stable_search(pkg_name))  # داخل المصدر فقط
    unstable_results = deduplicate(unstable_search(pkg_name))
    return stable_results, unstable_results  # ← نفس الحزمة قد تظهر مرتين!
```

**الحل المقترح:**
```python
def search(pkg_name: str) -> list[Package]:
    all_results = []
    for search_fn in [stable_search, unstable_search]:
        try:
            results = search_fn(pkg_name)
            all_results.extend(results)
        except Exception as e:
            console.print(f"[yellow]تحذير: فشل بحث {search_fn.__name__}: {e}[/yellow]")
    
    # إزالة التكرار بناءً على (name, version) مع الحفاظ على المصدر الأول
    seen = {}
    for pkg in sorted(all_results, key=lambda p: (p.source != "stable")):
        key = (pkg.name, pkg.version)
        if key not in seen:
            seen[key] = pkg
    
    return list(seen.values())
```

### 7. تحليل غير مستقر لصيغ ملفات Nix

**المكان:** `src/core/writer.py` — `detect_format()`

**المشكلة:**
- `"empty"` يتطلب `[\\s*]` تمامًا — `[ ]` و `[\n  # comment\n]` غير متعرفة.
- fallback إلى `"with_pkgs"` غير واضح.

**الحل المقترح:**
- إضافة fallback منطقي: إذا لم تُتعرف الصيغة، أظهر رسالة خطأ واضحة للمستخدم بدلاً من افتراض.
- إمكانياً: استخدام `nix-instantiate --parse` كفحص نحوي نهائي.

---

## معالجة الأخطاء ⚠️ أولوية متوسطة

### 8. لا إدارة للأخطاء في استدعاءات API

**المكان:** `src/api/stable.py`، `src/api/unstable.py`

**المشكلة:** `requests.post()` بدون `try/except`، `timeout`، أو فحص `status_code`.

**الحل المقترح:**
```python
try:
    response = requests.post(URL, headers=HEADERS, json={...}, timeout=10)
    response.raise_for_status()
    data = response.json()
except requests.exceptions.Timeout:
    console.print("[yellow]انتهت مهلة الاتصال — تحقق من اتصال الإنترنت[/yellow]")
    return []
except requests.exceptions.RequestException as e:
    console.print(f"[red]خطأ في الاتصال: {e}[/red]")
    return []
except ValueError:
    console.print("[red]استجابة غير صالحة من الخادم[/red]")
    return []
```

### 9. لا معالجة لأخطاء ملفات النظام

**المكان:** `src/core/writer.py`

**المشكلة:** `FileNotFoundError` و `PermissionError` غير مُعالجة.

**الحل المقترح:**
```python
def read_config(path: Path) -> str:
    try:
        return path.read_text()
    except FileNotFoundError:
        console.print(f"[red]ملف الإعداد غير موجود: {path}[/red]")
        raise
    except PermissionError:
        console.print(f"[red]صلاحيات غير كافية — جرّب: sudo nx install {pkg_name}[/red]")
        raise
```

---

## تجربة المستخدم ⚠️ أولوية منخفضة-متوسطة

### 10. لا يوجد رسائل توجيهية واضحة للمستخدم

**المشكلة:** الرسائل في `main.py` والـ prints العامة غير واضحة.

**الحل المقترح:**
- دمج `console.print` من `rich` في جميع الرسائل.
- إظهار رسائل مساعدة في كل خطوة:
  ```
  [cyan]🔎 البحث عن "firefox" في stable...[/cyan]
  [cyan]🔎 البحث في unstable...[/cyan]
  [green]✓ وجدت 4 حزم[/green]
  
  اختر رقم الحزمة (أو اتركه فارغاً للإلغاء): _
  ```

### 11. لا يوجد توثيق للاستخدام

**الحل المقترح:**
- إنشاء `USAGE.md` مع أمثلة عملية.
- إنشاء `man nx` page.

### 12. لا يوجد اختبارات

**الحل المقترح:**
- إضافة `pytest` + `tests/` directory.
- اختبارات لـ `detect_format()`، `add_package_*`, `remove_package()`, `validate_package_name()`.

---

## مكانيزمات لم تُنفّذ بعد (من project-status.md)

هذه هي المكانيزمات المذكورة في `project-status.md` كـ "ما لم يُكتمل بعد" لكنها **مهمة جدًا** للإصدار 1.0:

### ✅ 1. `remove_package` — لم تُنسخ إلى `writer.py`
الدالة موجودة في المحادثة لكن غير مُلحقة في الملف.

### ✅ 2. `is_package_exists`
```python
def is_package_exists(content: str, pkg_name: str) -> bool:
    # تبحث داخل نطاق systemPackages فقط
```
تتحقق من وجود الحزمة قبل الإضافة لتجنب التكرار.

### ✅ 3. `run_nixos_rebuild`
```python
def run_nixos_rebuild() -> bool:
    result = subprocess.run(["sudo", "nixos-rebuild", "switch"])
    return result.returncode == 0
```

### ✅ 4. دالة الكتابة النهائية
تجمع خطوات: `backup` → `add_package` → `write_file` → `run_rebuild` → `restore` إن فشل.

### ✅ 5. إعداد أول تشغيل (`first_setup`)
سؤال المستخدم كيف يريد إدارة الملفات:
```
[1] ملف واحد — nix-install.nix (packages + flakes)
[2] ملف للflakes + packages في configuration.nix
[3] ملف للpackages + flakes في flake.nix
[4] لا ملفات إضافية — كل شيء في ملفاته الأصلية
```
يُحفظ في `~/.config/nx/config.toml`.

### ✅ 6. دعم `flake.nix` و `nix-install-flakes.nix`
منطق إضافة وحذف الـ flakes في ملفاتها الخاصة.

### ✅ 7. صفحة man (`man nx`)
توثيق رسمي بـ man page.

### ✅ 8. تثبيت الأداة كأمر `nx`
إضافتها للـ PATH أو بناء derivation Nix لها.

---

## اقتراحات تحسين في وقت التطوير

| الأولوية | الاقتراح | الصعوبة | الوصف |
|---------|---------|--------|-------|
| 🔴 عالية | استبدال الترويسة المشفّرة بمتغيّر بيئة | سهل | كي لا يتم تسريق بيانات الاعتماد. |
| 🔴 عالية | إظافة `validate_package_name()` | سهل | منع حقن الأكواد في Nix. |
| 🟠 متوسطة | بناء `argparse` مع `install`/`remove`/`search` | متوسط | جعل الأداة قابلة للاستخدام. |
| 🟠 متوسطة | إضافة `try/except` حول `requests.post()` | سهل | منع تجمٌّ البرنامج. |
| 🟠 متوسطة | دمج نتائج البحث وإزالة التكرار بين المصادر | متوسط | تجربة مستخدم أفضل. |
| 🟡 منخفضة | إنشاء `pyproject.toml` | سهل | تحسين إدارة الحزم. |
| 🟡 منخفضة | إنشاء `.env.example` | سهل | توجيه المطورين. |
| 🟡 منخفضة | كتابة اختبارات أساسية بـ pytest | متوسط | ضمان استقرار الكود. |
| 🟢 تحسين مستقبلي | تعليقات `# nx-start` / `# nx-end` | متوسط | تسهيل إضافة وحذف الحزم. |
| 🟢 تحسين مستقبلي | `install_type` في `Package` | متوسط | دعم `programs.*` إضافة إلى `systemPackages`. |

---

## خارطة طريق للإصدار 1.0

### المرحلة 1: الأساسيات (قريب)
- [ ] استبدال التوكن بمتغيّر بيئة
- [ ] إضافة `validate_package_name()`
- [ ] بناء `main.py` مع `argparse` (`install`/`remove`)
- [ ] ربط `manager.search()` → `display.show_results()`
- [ ] إضافة `run_nixos_rebuild()`

### المرحلة 2: الاستقرار (متوسط)
- [ ] معالجة أخطاء API وملفات النظام
- [ ] دمج نتائج البحث وإزالة التكرار
- [ ] إضافة `is_package_exists()`
- [ ] كتابة اختبارات pytest

### المرحلة 3: الإكتمال (مستقبلي)
- [ ] إعداد أول تشغيل (first_setup)
- [ ] دعم Flake files (`flake.nix`)
- [ ] `man nx` page
- [ ] تثبيت كـ PATH derivation

---

## 📝 ملاحظات إضافية

- **NixOS-specific:** الأداة مصممة خصيصًا لـ NixOS — يجب أن تتعامل مع `configuration.nix`، `flake.nix`، و `nixos-rebuild` بوعي كامل.
- **Python 3.11+:** يدعم `str | None`، لكنه لا يستخدم type hints في كل مكان بعد.
- **بيئة التطوير:** الموجودة في `/etc/nixos-test/` — لا تُلمس `/etc/nixos/` أثناء التطوير.

---

> **تم إنشاء هذا الملف:** أغسطس 2026  
> **لمزيد من السياق:** اراجع `project-status.md` في جذر المشروع  
> **للمراجعة:** فريق التطوير وأي مطور آخر ينضم للمشروع