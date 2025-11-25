import 'package:flutter/material.dart';
import 'package:animate_do/animate_do.dart';
import '../chat_screen.dart';

class DevToolsTab extends StatelessWidget {
  // قائمة الأدوات (تم توسيعها لتشمل وصفاً وألواناً)
  final List<_ToolItem> tools = [
    _ToolItem(
      title: "مصحح الأخطاء",
      desc: "اكتشف الأخطاء البرمجية واحصل على حلول فورية.",
      icon: Icons.bug_report_rounded,
      color: Colors.redAccent,
      prompt: "أنت خبير في تصحيح الأكواد (Debugging). سأعطيك كوداً، وعليك اكتشاف الأخطاء فيه وشرح كيفية إصلاحها.",
    ),
    _ToolItem(
      title: "شرح الكود",
      desc: "فهم المنطق خلف الأكواد المعقدة خطوة بخطوة.",
      icon: Icons.description_rounded,
      color: Colors.blue,
      prompt: "أنت معلم برمجة. سأعطيك كوداً، وعليك شرحه لي سطراً بسطر بأسلوب مبسط وواضح.",
    ),
    _ToolItem(
      title: "تحسين الكود",
      desc: "تحويل الكود إلى Clean Code أكثر كفاءة.",
      icon: Icons.cleaning_services_rounded,
      color: Colors.green,
      prompt: "أنت خبير في جودة البرمجيات (Code Quality). قم بإعادة صياغة الكود التالي ليكون أنظف (Clean Code)، أسرع، وأكثر قابلية للقراءة.",
    ),
    _ToolItem(
      title: "أفكار مشاريع",
      desc: "احصل على إلهام لمشروعك البرمجي القادم.",
      icon: Icons.lightbulb_rounded,
      color: Colors.amber,
      prompt: "اقترح عليّ 5 أفكار مشاريع برمجية مبتكرة تناسب مستواي (مبتدئ/متوسط) مع ذكر التقنيات المقترحة لكل مشروع.",
    ),
    _ToolItem(
      title: "توثيق الكود",
      desc: "كتابة Documentation والتعليقات تلقائياً.",
      icon: Icons.article_rounded,
      color: Colors.purple,
      prompt: "قم بكتابة توثيق (Documentation) شامل للكود التالي، مع إضافة تعليقات توضيحية لكل دالة.",
    ),
    _ToolItem(
      title: "إنشاء اختبارات",
      desc: "توليد Unit Tests لضمان جودة الكود.",
      icon: Icons.check_circle_outline_rounded,
      color: Colors.teal,
      prompt: "اكتب اختبارات وحدة (Unit Tests) شاملة للكود التالي لتغطية جميع الحالات الممكنة.",
    ),
  ];

  @override
  Widget build(BuildContext context) {
    // متغيرات الثيم
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final textColor = isDark ? Colors.white : Colors.black87;
    final subTextColor = isDark ? Colors.grey[400] : Colors.grey[600];

    return Scaffold(
      backgroundColor: Theme.of(context).scaffoldBackgroundColor,
      body: Padding(
        padding: EdgeInsets.fromLTRB(20, 50, 20, 0), // مسافة علوية للعنوان
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // رأس الصفحة
            FadeInDown(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text("أدوات المطور", style: TextStyle(fontSize: 28, fontWeight: FontWeight.bold, color: Color(0xFF6C63FF))),
                  SizedBox(height: 5),
                  Text("مجموعة أدوات ذكية لتسريع إنتاجيتك", style: TextStyle(color: Colors.grey, fontSize: 14)),
                ],
              ),
            ),
            
            SizedBox(height: 25),

            // شبكة الأدوات
            Expanded(
              child: GridView.builder(
                padding: EdgeInsets.only(bottom: 100), // مسافة للشريط السفلي
                gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
                  crossAxisCount: 2, // عمودين
                  crossAxisSpacing: 15,
                  mainAxisSpacing: 15,
                  childAspectRatio: 0.85, // نسبة الطول للعرض (مستطيل رأسي قليلاً لاستيعاب الوصف)
                ),
                itemCount: tools.length,
                itemBuilder: (ctx, i) {
                  return FadeInUp(
                    delay: Duration(milliseconds: i * 100), // تأثير تتابع
                    child: _buildToolCard(context, tools[i], isDark, textColor, subTextColor!),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildToolCard(BuildContext context, _ToolItem tool, bool isDark, Color titleColor, Color descColor) {
    return GestureDetector(
      onTap: () {
        Navigator.push(context, MaterialPageRoute(
          builder: (_) => ChatScreen(title: tool.title, sysPrompt: tool.prompt)
        ));
      },
      child: Container(
        padding: EdgeInsets.all(15),
        decoration: BoxDecoration(
          color: Theme.of(context).cardColor,
          borderRadius: BorderRadius.circular(20),
          boxShadow: [BoxShadow(color: Colors.black.withOpacity(isDark ? 0.3 : 0.05), blurRadius: 10, offset: Offset(0, 4))],
          border: isDark ? Border.all(color: Colors.white10) : null,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // الأيقونة الملونة
            Container(
              padding: EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: tool.color.withOpacity(0.1),
                shape: BoxShape.circle,
              ),
              child: Icon(tool.icon, color: tool.color, size: 28),
            ),
            Spacer(),
            // العنوان
            Text(
              tool.title,
              style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: titleColor),
            ),
            SizedBox(height: 5),
            // الوصف
            Text(
              tool.desc,
              style: TextStyle(fontSize: 11, color: descColor, height: 1.4),
              maxLines: 3,
              overflow: TextOverflow.ellipsis,
            ),
            SizedBox(height: 5),
          ],
        ),
      ),
    );
  }
}

// كلاس بسيط لتنظيم البيانات
class _ToolItem {
  final String title;
  final String desc;
  final IconData icon;
  final Color color;
  final String prompt;

  _ToolItem({
    required this.title, 
    required this.desc, 
    required this.icon, 
    required this.color, 
    required this.prompt
  });
}