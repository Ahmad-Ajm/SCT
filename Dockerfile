# SCT — أداة الزحف وتدقيق SEO
# صورة جاهزة للتشغيل: تحوي Python + Chromium (لتصيير JS وتقارير PDF).
# نبني على صورة Playwright الرسمية كي يكون المتصفّح ومكتباته جاهزة.
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

# إعدادات بايثون أنظف داخل الحاوية
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 1) المتطلبات أولاً للاستفادة من طبقات الكاش
COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt \
    # المتصفّح مضمّن في الصورة الأساسية، لكن نضمنه (idempotent)
    && python -m playwright install chromium

# 2) كود المصدر (تستبعد .dockerignore البيانات/الأسرار)
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
