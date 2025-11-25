import 'dart:math';
import 'package:flutter/material.dart';
import 'package:animate_do/animate_do.dart';
import 'package:google_fonts/google_fonts.dart';

class InspirationTab extends StatelessWidget {
  // قائمة الاقتباسات المتجددة
  final List<Map<String, String>> _quotes = [
    {
      "text": "الجميع يجب أن يتعلم كيفية برمجة الكمبيوتر، لأنه يعلمك كيف تفكر.",
      "author": "ستيف جوبز"
    },
    {
      "text": "البرمجة ليست حول ما تعرفه، بل حول ما يمكنك اكتشافه.",
      "author": "كريس باين"
    },
    {
      "text": "الكود هو الشعر الحديث.",
      "author": "مجهول"
    },
    {
      "text": "أفضل طريقة للتنبؤ بالمستقبل هي اختراعه.",
      "author": "آلان كاي"
    },
    {
      "text": "الخبرة هي اسم يطلقه الجميع على أخطائهم.",
      "author": "أوسكار وايلد"
    },
  ];

  @override
  Widget build(BuildContext context) {
    // اختيار اقتباس عشوائي
    final randomQuote = _quotes[Random().nextInt(_quotes.length)];
    
    // متغيرات الثيم
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final textColor = isDark ? Colors.white : Colors.black87;
    final cardColor = Theme.of(context).cardColor;

    return SingleChildScrollView(
      padding: EdgeInsets.fromLTRB(20, 50, 20, 100),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 1. بانر الترحيب (Hero Banner)
          FadeInDown(
            child: Container(
              width: double.infinity,
              padding: EdgeInsets.all(25),
              decoration: BoxDecoration(
                gradient: LinearGradient(
                  colors: [Color(0xFF8E2DE2), Color(0xFF4A00E0)],
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                ),
                borderRadius: BorderRadius.circular(25),
                boxShadow: [BoxShadow(color: Color(0xFF4A00E0).withOpacity(0.3), blurRadius: 15, offset: Offset(0, 8))],
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Container(
                    padding: EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                    decoration: BoxDecoration(color: Colors.white24, borderRadius: BorderRadius.circular(20)),
                    child: Text("لماذا نبرمج؟", style: TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.bold)),
                  ),
                  SizedBox(height: 15),
                  Text(
                    "البرمجة هي لغة المستقبل والقوة التي تبني الحلول التقنية الحديثة.",
                    style: TextStyle(height: 1.5, color: Colors.white, fontSize: 16, fontWeight: FontWeight.w600),
                  ),
                ],
              ),
            ),
          ),
          
          SizedBox(height: 30),

          // 2. كارت الاقتباس المتجدد
          FadeInUp(
            delay: Duration(milliseconds: 200),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text("جرعة إلهام 💡", style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: textColor)),
                SizedBox(height: 15),
                Container(
                  padding: EdgeInsets.all(20),
                  decoration: BoxDecoration(
                    color: cardColor,
                    borderRadius: BorderRadius.circular(20),
                    border: Border.all(color: Colors.amber.withOpacity(0.3)),
                    boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 10)],
                  ),
                  child: Row(
                    children: [
                      Icon(Icons.format_quote_rounded, color: Colors.amber, size: 40),
                      SizedBox(width: 15),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              randomQuote['text']!,
                              style: GoogleFonts.tajawal(fontSize: 16, height: 1.5, fontStyle: FontStyle.italic, color: textColor),
                            ),
                            SizedBox(height: 10),
                            Text(
                              "- ${randomQuote['author']}",
                              style: TextStyle(color: Colors.grey, fontSize: 12, fontWeight: FontWeight.bold),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),

          SizedBox(height: 30),

          // 3. مسارات التعلم التفاعلية
          Text("اختر مسارك 🚀", style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: textColor)),
          SizedBox(height: 15),
          
          _buildPathCard(
            context, 
            "تطوير المواقع (Web)", 
            "HTML, CSS, JS, React", 
            "ابنِ مواقع تفاعلية تعمل على كل الأجهزة.",
            Icons.web_rounded, 
            Colors.orange, 
            isDark
          ),
          _buildPathCard(
            context, 
            "تطبيقات الموبايل (Mobile)", 
            "Flutter, Dart, Kotlin", 
            "تطبيق واحد يعمل على آيفون وأندرويد.",
            Icons.phone_android_rounded, 
            Colors.blue, 
            isDark
          ),
          _buildPathCard(
            context, 
            "الذكاء الاصطناعي (AI)", 
            "Python, TensorFlow", 
            "علم الآلة كيف تفكر وتتوقع المستقبل.",
            Icons.psychology_rounded, 
            Colors.purple, 
            isDark
          ),
          _buildPathCard(
            context, 
            "الأمن السيبراني (Security)", 
            "Network, Linux, Python", 
            "دافع عن الأنظمة واكتشف الثغرات.",
            Icons.security_rounded, 
            Colors.red, 
            isDark
          ),
        ],
      ),
    );
  }

  Widget _buildPathCard(BuildContext context, String title, String techs, String desc, IconData icon, Color color, bool isDark) {
    return FadeInUp(
      child: GestureDetector(
        onTap: () {
          // إظهار تفاصيل المسار عند الضغط
          showModalBottomSheet(
            context: context,
            backgroundColor: Colors.transparent,
            builder: (ctx) => Container(
              padding: EdgeInsets.all(25),
              decoration: BoxDecoration(
                color: isDark ? Color(0xFF1E1E2C) : Colors.white,
                borderRadius: BorderRadius.vertical(top: Radius.circular(30)),
              ),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      CircleAvatar(backgroundColor: color.withOpacity(0.1), child: Icon(icon, color: color)),
                      SizedBox(width: 15),
                      Text(title, style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: isDark ? Colors.white : Colors.black)),
                    ],
                  ),
                  SizedBox(height: 20),
                  Text("ماذا ستتعلم؟", style: TextStyle(fontWeight: FontWeight.bold, color: Colors.grey)),
                  Text(desc, style: TextStyle(fontSize: 16, height: 1.5, color: isDark ? Colors.white70 : Colors.black87)),
                  SizedBox(height: 15),
                  Text("التقنيات المطلوبة:", style: TextStyle(fontWeight: FontWeight.bold, color: Colors.grey)),
                  Text(techs, style: TextStyle(fontSize: 16, color: color, fontWeight: FontWeight.bold)),
                  SizedBox(height: 30),
                  SizedBox(
                    width: double.infinity,
                    child: ElevatedButton(
                      onPressed: () => Navigator.pop(ctx),
                      child: Text("فهمت، شكراً"),
                      style: ElevatedButton.styleFrom(backgroundColor: color, foregroundColor: Colors.white, padding: EdgeInsets.all(15)),
                    ),
                  )
                ],
              ),
            ),
          );
        },
        child: Container(
          margin: EdgeInsets.only(bottom: 15),
          decoration: BoxDecoration(
            color: Theme.of(context).cardColor,
            borderRadius: BorderRadius.circular(20),
            boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.03), blurRadius: 10, offset: Offset(0, 4))],
          ),
          child: ListTile(
            contentPadding: EdgeInsets.symmetric(horizontal: 20, vertical: 10),
            leading: Container(
              padding: EdgeInsets.all(12),
              decoration: BoxDecoration(color: color.withOpacity(0.1), borderRadius: BorderRadius.circular(15)),
              child: Icon(icon, color: color, size: 28),
            ),
            title: Text(title, style: TextStyle(fontWeight: FontWeight.bold, color: isDark ? Colors.white : Colors.black87)),
            subtitle: Text(techs, style: TextStyle(color: Colors.grey[600], fontSize: 12)),
            trailing: Icon(Icons.arrow_forward_ios_rounded, size: 16, color: Colors.grey[300]),
          ),
        ),
      ),
    );
  }
}