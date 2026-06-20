# SCT — أداة الزحف وتدقيق SEO
# صورة جاهزة للتشغيل: تحوي Python + Chromium (لتصيير JS وتقارير PDF).
#
# ─────────────────────────────────────────────────────────────────────────────
# لماذا multi-stage هنا؟
# صور Playwright الرسمية ضخمة لأنها تحوي ثنائيات Chromium + كل مكتبات النظام
# اللازمة لتشغيله (libnss، libatk، fonts، إلخ). لو حاولنا تنحيف runtime عبر
# الانتقال إلى python:slim لاضطُررنا لإعادة تنزيل Chromium + تثبيت كل
# تبعيّات النظام يدوياً — وهذا نادراً ما يستحقّ الحجم الموفّر، ويُدخل
# هشاشة في التوافق مع إصدار Playwright.
#
# لذا نُبقي نفس الصورة الأساسية في الـbuilder وفي الـruntime، ونستخدم
# multi-stage لفصل واضح:
#   - builder: pip cache + أيّ تبعيّات بناء (compiler/headers لو احتجناها)
#   - runtime: فقط site-packages + executables الناتجة + كود المصدر
# الفائدة العملية: الـruntime لا يحمل آثار pip/wheel/cache، طبقاته أنظف،
# وأيّ build-tooling نُضيفه مستقبلاً (مثل gcc لـ wheels مصدريّة) لا يتسرّب
# للصورة النهائية.
# ─────────────────────────────────────────────────────────────────────────────

# ════════════════════════════════════════════════════════════════════════════
# Stage 1 — builder: نُثبّت المتطلبات ونضمن وجود Chromium.
# ════════════════════════════════════════════════════════════════════════════
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# المتطلبات أولاً للاستفادة من طبقات الكاش — أي تغيير في requirements.txt فقط
# يُعيد تشغيل هذه الطبقة دون لمس باقي المصدر.
COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt \
    # المتصفّح مضمّن في الصورة الأساسية، لكن نضمنه (idempotent).
    # يُحفظ افتراضياً في /ms-playwright وهو موجود في الصورة الأساسية للـruntime أيضاً.
    && python -m playwright install chromium

# ════════════════════════════════════════════════════════════════════════════
# Stage 2 — runtime: نفس الصورة الأساسية (Chromium + libs جاهزة)،
# لكن ننسخ فقط site-packages والـexecutables من الـbuilder + كود المصدر.
# ════════════════════════════════════════════════════════════════════════════
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# ننقل حزم Python المُثبّتة من الـbuilder بدلاً من إعادة تشغيل pip.
# المسارات قياسيّة في صورة Playwright (Python 3.10 على jammy).
COPY --from=builder /usr/lib/python3/dist-packages /usr/lib/python3/dist-packages
COPY --from=builder /usr/local/lib/python3.10/dist-packages /usr/local/lib/python3.10/dist-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# كود المصدر (.dockerignore يستبعد البيانات/الأسرار).
COPY . .

# v1.09: تشغيل كمستخدم غير-root لتقليل blast radius لأي ثغرة في الحاوية.
# webapp_jobs/ يحتاج كتابة ⇒ نُعطي ملكيّتها للمستخدم الجديد.
RUN useradd --create-home --shell /bin/bash sct \
    && mkdir -p /app/webapp_jobs \
    && chown -R sct:sct /app
USER sct

# الواجهة المرئية
EXPOSE 8000

# v1.10-C1 (M-11): HEALTHCHECK — orchestrators (Docker compose, K8s) تعرف هل
# الـapp يردّ فعلاً، لا فقط هل الـprocess على قيد الحياة.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).getcode()==200 else 1)" \
        || exit 1

# لا تُضمّن أي مفاتيح في الصورة — تُمرَّر وقت التشغيل عبر -e أو env_file/.env
CMD ["python", "webapp/run.py", "--host", "0.0.0.0", "--port", "8000"]
