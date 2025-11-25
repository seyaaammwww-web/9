import 'package:flutter/material.dart';
import 'package:animate_do/animate_do.dart';
import '../chat_screen.dart';

class ChatTab extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    // متغيرات الثيم لضمان التناسق مع الوضع الليلي والنهاري
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final primaryColor = Theme.of(context).primaryColor;
    final textColor = isDark ? Colors.white : Colors.black87;
    final cardColor = Theme.of(context).cardColor;

    return SingleChildScrollView(
      padding: const EdgeInsets.all(25.0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          SizedBox(height: 20),
          
          // 1. أيقونة الروبوت المتحركة (مع تأثير تنفس/Breathing)
          Pulse(
            infinite: true,
            duration: Duration(seconds: 3),
            child: Container(
              padding: EdgeInsets.all(30),
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                gradient: LinearGradient(
                  colors: [primaryColor.withOpacity(0.2), primaryColor.withOpacity(0.05)],
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                ),
                border: Border.all(color: primaryColor.withOpacity(0.3), width: 2),
                boxShadow: [
                  BoxShadow(
                    color: primaryColor.withOpacity(0.1),
                    blurRadius: 40,
                    spreadRadius: 5,
                  )
                ]
              ),
              child: Icon(Icons.smart_toy_rounded, size: 80, color: primaryColor),
            ),
          ),
          
          SizedBox(height: 30),

          // 2. نصوص الترحيب
          FadeInDown(
            child: Column(
              children: [
                Text(
                  "المعلم الذكي",
                  style: TextStyle(fontSize: 28, fontWeight: FontWeight.bold, color: textColor),
                ),
                SizedBox(height: 10),
                Container(
                  padding: EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                  decoration: BoxDecoration(
                    color: Colors.green.withOpacity(0.1),
                    borderRadius: BorderRadius.circular(20),
                    border: Border.all(color: Colors.green.withOpacity(0.3))
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      CircleAvatar(radius: 4, backgroundColor: Colors.green),
                      SizedBox(width: 6),
                      Text("متصل الآن • جاهز للمساعدة", style: TextStyle(fontSize: 12, color: Colors.green, fontWeight: FontWeight.bold)),
                    ],
                  ),
                ),
                SizedBox(height: 15),
                Text(
                  "اسألني عن أي كود، أو اطلب شرحاً لمفهوم برمجي،\nوسأقوم بتبسيطه لك فوراً.",
                  textAlign: TextAlign.center,
                  style: TextStyle(fontSize: 14, color: Colors.grey, height: 1.6),
                ),
              ],
            ),
          ),

          SizedBox(height: 40),

          // 3. اقتراحات سريعة (Quick Prompts) - ميزة جديدة
          FadeInUp(
            delay: Duration(milliseconds: 200),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text("جرب أن تسأل:", style: TextStyle(fontWeight: FontWeight.bold, color: textColor)),
                SizedBox(height: 15),
                Wrap(
                  spacing: 10,
                  runSpacing: 10,
                  alignment: WrapAlignment.center,
                  children: [
                    _buildQuickPrompt(context, "🐞 اكتشف الخطأ في الكود", primaryColor, isDark),
                    _buildQuickPrompt(context, "📚 اشرح لي الـ OOP", primaryColor, isDark),
                    _buildQuickPrompt(context, "🚀 كيف أبدأ في Flutter؟", primaryColor, isDark),
                    _buildQuickPrompt(context, "📝 لخص لي هذا الدرس", primaryColor, isDark),
                  ],
                ),
              ],
            ),
          ),

          SizedBox(height: 40),

          // 4. زر البدء الرئيسي
          FadeInUp(
            delay: Duration(milliseconds: 400),
            child: SizedBox(
              width: double.infinity,
              height: 55,
              child: ElevatedButton.icon(
                onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => ChatScreen())),
                icon: Icon(Icons.chat_bubble_outline),
                label: Text("بدء محادثة جديدة"),
                style: ElevatedButton.styleFrom(
                  backgroundColor: primaryColor,
                  foregroundColor: Colors.white,
                  elevation: 8,
                  shadowColor: primaryColor.withOpacity(0.4),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(15)),
                  textStyle: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  // ودجت مساعدة لبناء أزرار الاقتراحات
  Widget _buildQuickPrompt(BuildContext context, String text, Color color, bool isDark) {
    return ActionChip(
      label: Text(text),
      labelStyle: TextStyle(color: isDark ? Colors.white70 : Colors.black87, fontSize: 12),
      backgroundColor: isDark ? Colors.grey[800] : Colors.white,
      side: BorderSide(color: Colors.grey.withOpacity(0.3)),
      padding: EdgeInsets.symmetric(horizontal: 8, vertical: 8),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      onPressed: () {
        // عند الضغط، نفتح الشات ونمرر السؤال مباشرة (اختياري، حالياً يفتح الشات فقط)
        Navigator.push(context, MaterialPageRoute(builder: (_) => ChatScreen())); 
      },
    );
  }
}