# كيف تجد GA4 property_id؟

`property_id` هو معرّف الـProperty في Google Analytics 4 — رقم من 9-10 خانات (مثل
`123456789`). تحتاجه SCT لجلب بيانات GA4.

## الطريقة الأولى — من واجهة GA4 (الأسرع)

1. افتح [Google Analytics](https://analytics.google.com/) واختر الـ Property من
   القائمة العلوية.
2. اضغط **⚙️ Admin** أسفل القائمة الجانبية.
3. في العمود الأوسط («Property») اضغط **Property details** (أو **Property settings**).
4. سترى **Property ID** بوضوح في أعلى الصفحة — انسخه.

> الرقم يبدأ عادةً بـ`2`، `3`، `4` أو `5` ويتكوّن من 9-10 أرقام.

## الطريقة الثانية — من واجهة SCT (الأسهل بعد ربط Google)

بعد ربط Google من تبويب **🔌 التكاملات والذكاء** في SCT:

1. في بطاقة **Google Analytics 4** اضغط **📋 جلب خصائص GA4**.
2. ستظهر قائمة بكلّ الـ Properties التي تملك صلاحية عليها.
3. اختر واحدة — يتعبّأ الـ `property_id` تلقائياً.

## الفرق بين Property ID و Measurement ID

- **Property ID**: رقم تقريباً 9-10 خانات (`123456789`) — هذا ما تحتاجه SCT.
- **Measurement ID**: يبدأ بـ`G-` (مثل `G-XXXXXXXXXX`) — يُستخدم في وسم gtag على
  الموقع، **ليس هو** المطلوب هنا.

## الصلاحيات المطلوبة

للوصول إلى بيانات الـ Property حسابك يحتاج صلاحية **Viewer** على الأقلّ في GA4:

- افتح GA4 → **⚙️ Admin** → **Property Access Management**.
- إن لم تكن في القائمة، اطلب من مالك الـ Property إضافتك (Email + role = Viewer كافٍ).
