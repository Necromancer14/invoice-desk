export type Lang = "en" | "ar";

const ar: Record<string, string> = {
  Dashboard: "لوحة المتابعة", "Upload invoices": "رفع الفواتير", Runs: "العمليات", "Review queue": "قائمة المراجعة", Rules: "القواعد",
  Evaluation: "التقييم", "Audit log": "سجل التدقيق", Settings: "الإعدادات", Approve: "اعتماد", Reject: "رفض", "Sign out": "تسجيل الخروج",
  "Sign in as": "الدخول بصفة", Viewer: "مشاهد", Reviewer: "مراجع", Admin: "مدير", Approved: "معتمدة", "Needs review": "تحتاج مراجعة",
  Rejected: "مرفوضة", Failed: "فشلت", Save: "حفظ", Cancel: "إلغاء", Search: "بحث", "Upload": "رفع", Language: "اللغة", Theme: "المظهر",
  "Invoice number": "رقم الفاتورة", Seller: "البائع", Total: "الإجمالي", Status: "الحالة", File: "الملف", Created: "التاريخ",
  "Approved by a person": "اعتمدها مراجع", "Rejected by a person": "رفضها مراجع", Processing: "قيد المعالجة", Queued: "في الانتظار",
};

export function makeT(lang: Lang) {
  return (s: string) => (lang === "ar" ? ar[s] ?? s : s);
}
