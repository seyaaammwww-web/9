import 'package:flutter/material.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:fl_chart/fl_chart.dart';
import 'package:lottie/lottie.dart';
import 'package:animate_do/animate_do.dart';
import 'dart:math';
import '../achievements_screen.dart'; // للربط بصفحة الأوسمة

class AnalyticsTab extends StatelessWidget {
  final User? user = FirebaseAuth.instance.currentUser;

  // دالة لحساب المستوى (كل 500 نقطة = مستوى)
  int _calculateLevel(int points) {
    return (points / 500).floor() + 1;
  }

  // دالة لحساب التقدم نحو المستوى القادم (من 0.0 إلى 1.0)
  double _calculateProgress(int points) {
    return (points % 500) / 500;
  }

  @override
  Widget build(BuildContext context) {
    // تحديد الألوان حسب الثيم
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final textColor = isDark ? Colors.white : Colors.black87;
    final cardColor = Theme.of(context).cardColor;

    return Scaffold(
      backgroundColor: Colors.transparent,
      body: StreamBuilder<DocumentSnapshot>(
        stream: FirebaseFirestore.instance.collection('users').doc(user?.uid).snapshots(),
        builder: (context, snapshot) {
          if (!snapshot.hasData) return Center(child: CircularProgressIndicator());

          var userData = snapshot.data!.data() as Map<String, dynamic>;
          int points = userData['totalPoints'] ?? 0;
          int streak = userData['daily_streak'] ?? 0;
          
          int level = _calculateLevel(points);
          double levelProgress = _calculateProgress(points);
          int pointsToNextLevel = 500 - (points % 500);

          return SingleChildScrollView(
            padding: EdgeInsets.all(20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // 1. رأس الصفحة (المستوى والستريك)
                _buildHeader(context, points, streak, level, levelProgress, pointsToNextLevel),
                
                SizedBox(height: 25),

                // 2. الرسم البياني للنشاط
                Text("نشاطك الأسبوعي 📊", style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: textColor)),
                SizedBox(height: 15),
                Container(
                  height: 220,
                  padding: EdgeInsets.fromLTRB(10, 25, 10, 10),
                  decoration: BoxDecoration(
                    color: cardColor,
                    borderRadius: BorderRadius.circular(20),
                    boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 10)],
                  ),
                  child: _buildWeeklyChart(context, isDark),
                ),

                SizedBox(height: 25),

                // 3. أزرار الوصول السريع
                Row(
                  children: [
                    Expanded(
                      child: _buildActionBtn(
                        context, 
                        "الإنجازات", 
                        Icons.emoji_events, 
                        Colors.amber, 
                        () => Navigator.push(context, MaterialPageRoute(builder: (_) => AchievementsScreen()))
                      ),
                    ),
                    SizedBox(width: 15),
                    Expanded(
                      child: _buildActionBtn(
                        context, 
                        "شارك تقدمك", 
                        Icons.share, 
                        Colors.blue, 
                        () => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("تم نسخ رابط إنجازك! 🚀")))
                      ),
                    ),
                  ],
                ),

                SizedBox(height: 25),

                // 4. لوحة المتصدرين (Leaderboard)
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text("لوحة الأبطال 🏆", style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: textColor)),
                    Text("أفضل الطلاب", style: TextStyle(fontSize: 12, color: Colors.grey)),
                  ],
                ),
                SizedBox(height: 15),
                _buildLeaderboard(context, isDark),
                
                SizedBox(height: 80), // مساحة إضافية في الأسفل
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _buildHeader(BuildContext context, int points, int streak, int level, double progress, int pointsToNext) {
    return FadeInDown(
      child: Container(
        padding: EdgeInsets.all(20),
        decoration: BoxDecoration(
          gradient: LinearGradient(
            colors: [Color(0xFF6C63FF), Color(0xFF4834D4)],
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
          ),
          borderRadius: BorderRadius.circular(25),
          boxShadow: [BoxShadow(color: Color(0xFF6C63FF).withOpacity(0.4), blurRadius: 15, offset: Offset(0, 8))],
        ),
        child: Column(
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text("المستوى $level", style: TextStyle(color: Colors.white, fontSize: 28, fontWeight: FontWeight.bold)),
                    SizedBox(height: 5),
                    Container(
                      padding: EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                      decoration: BoxDecoration(color: Colors.white24, borderRadius: BorderRadius.circular(10)),
                      child: Text("$points XP المجموع", style: TextStyle(color: Colors.white, fontSize: 12)),
                    ),
                  ],
                ),
                // أيقونة الستريك المتحركة
                Container(
                  padding: EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                  decoration: BoxDecoration(
                    color: Colors.black.withOpacity(0.2), 
                    borderRadius: BorderRadius.circular(20),
                    border: Border.all(color: Colors.orange.withOpacity(0.5))
                  ),
                  child: Row(
                    children: [
                      // استخدام أيقونة ثابتة مع تأثير أو Lottie إذا توفر الرابط
                      Lottie.network(
                        'https://assets10.lottiefiles.com/packages/lf20_9xRk0r.json', // رابط أنيميشن نار
                        height: 30,
                        width: 30,
                        errorBuilder: (context, error, stackTrace) => Icon(Icons.local_fire_department, color: Colors.orange, size: 30),
                      ),
                      SizedBox(width: 5),
                      Text("$streak يوم", style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 16)),
                    ],
                  ),
                )
              ],
            ),
            SizedBox(height: 25),
            // شريط التقدم
            Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                ClipRRect(
                  borderRadius: BorderRadius.circular(10),
                  child: LinearProgressIndicator(
                    value: progress,
                    backgroundColor: Colors.black12,
                    color: Colors.amber,
                    minHeight: 12,
                  ),
                ),
                SizedBox(height: 8),
                Text("باقي $pointsToNext نقطة للمستوى القادم", style: TextStyle(color: Colors.white70, fontSize: 12))
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildWeeklyChart(BuildContext context, bool isDark) {
    return BarChart(
      BarChartData(
        alignment: BarChartAlignment.spaceAround,
        maxY: 100,
        gridData: FlGridData(show: false),
        borderData: FlBorderData(show: false),
        titlesData: FlTitlesData(
          show: true,
          bottomTitles: AxisTitles(
            sideTitles: SideTitles(
              showTitles: true,
              reservedSize: 30,
              getTitlesWidget: (value, meta) {
                const days = ['سبت', 'أحد', 'اثنين', 'ثلاثاء', 'أربعاء', 'خميس', 'جمعة'];
                if (value.toInt() >= 0 && value.toInt() < days.length) {
                  return Padding(
                    padding: const EdgeInsets.only(top: 8.0),
                    child: Text(days[value.toInt()], style: TextStyle(color: Colors.grey, fontSize: 10, fontWeight: FontWeight.bold)),
                  );
                }
                return Text('');
              },
            ),
          ),
          leftTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
          topTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
          rightTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
        ),
        barGroups: List.generate(7, (index) {
          // محاكاة بيانات (يمكن ربطها ببيانات حقيقية لاحقاً)
          double randomValue = (Random().nextInt(60) + 20).toDouble();
          bool isToday = index == 6; // افتراض أن اليوم هو الجمعة
          return BarChartGroupData(
            x: index,
            barRods: [
              BarChartRodData(
                toY: isToday ? 85 : randomValue, 
                color: isToday ? Color(0xFF6C63FF) : (isDark ? Colors.grey[800] : Colors.grey[200]),
                width: 14,
                borderRadius: BorderRadius.circular(6),
                backDrawRodData: BackgroundBarChartRodData(
                  show: true,
                  toY: 100,
                  color: isDark ? Colors.white.withOpacity(0.05) : Colors.grey.withOpacity(0.1),
                ),
              )
            ],
          );
        }),
      ),
    );
  }

  Widget _buildActionBtn(BuildContext context, String label, IconData icon, Color color, VoidCallback onTap) {
    return ElevatedButton(
      onPressed: onTap,
      style: ElevatedButton.styleFrom(
        backgroundColor: color.withOpacity(0.1),
        foregroundColor: color,
        elevation: 0,
        padding: EdgeInsets.symmetric(vertical: 15),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(15)),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(icon, size: 20),
          SizedBox(width: 8),
          Text(label, style: TextStyle(fontWeight: FontWeight.bold)),
        ],
      ),
    );
  }

  Widget _buildLeaderboard(BuildContext context, bool isDark) {
    return StreamBuilder<QuerySnapshot>(
      // جلب أفضل 5 طلاب
      stream: FirebaseFirestore.instance
          .collection('users')
          .where('role', isEqualTo: 'student')
          .orderBy('totalPoints', descending: true)
          .limit(5)
          .snapshots(),
      builder: (context, snapshot) {
        if (!snapshot.hasData) return Center(child: CircularProgressIndicator());
        
        var docs = snapshot.data!.docs;
        if (docs.isEmpty) return Text("لا توجد بيانات كافية", style: TextStyle(color: Colors.grey));

        return Column(
          children: List.generate(docs.length, (index) {
            var data = docs[index].data() as Map<String, dynamic>;
            bool isMe = data['uid'] == user?.uid; // لتمييز المستخدم الحالي (يجب التأكد من وجود حقل uid في المستند أو استخدام doc.id)
            
            // تحديد أيقونة المركز
            Widget rankIcon;
            if (index == 0) rankIcon = Text("🥇", style: TextStyle(fontSize: 20));
            else if (index == 1) rankIcon = Text("🥈", style: TextStyle(fontSize: 20));
            else if (index == 2) rankIcon = Text("🥉", style: TextStyle(fontSize: 20));
            else rankIcon = Text("#${index + 1}", style: TextStyle(fontWeight: FontWeight.bold, color: Colors.grey));

            return FadeInUp(
              delay: Duration(milliseconds: index * 100),
              child: Container(
                margin: EdgeInsets.only(bottom: 10),
                padding: EdgeInsets.symmetric(horizontal: 15, vertical: 12),
                decoration: BoxDecoration(
                  color: isMe ? Color(0xFF6C63FF).withOpacity(0.1) : Theme.of(context).cardColor,
                  borderRadius: BorderRadius.circular(15),
                  border: isMe ? Border.all(color: Color(0xFF6C63FF), width: 1) : null,
                  boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.02), blurRadius: 5)],
                ),
                child: Row(
                  children: [
                    SizedBox(width: 30, child: Center(child: rankIcon)),
                    SizedBox(width: 10),
                    CircleAvatar(
                      radius: 20,
                      backgroundColor: Colors.grey[200],
                      backgroundImage: data['photoUrl'] != null ? NetworkImage(data['photoUrl']) : null,
                      child: data['photoUrl'] == null ? Icon(Icons.person, color: Colors.grey) : null,
                    ),
                    SizedBox(width: 15),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            data['name'] ?? "مستخدم", 
                            style: TextStyle(fontWeight: FontWeight.bold, color: isDark ? Colors.white : Colors.black87)
                          ),
                          if (isMe) Text("أنت", style: TextStyle(fontSize: 10, color: Color(0xFF6C63FF))),
                        ],
                      )
                    ),
                    Container(
                      padding: EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                      decoration: BoxDecoration(
                        color: Colors.amber.withOpacity(0.1),
                        borderRadius: BorderRadius.circular(10)
                      ),
                      child: Text("${data['totalPoints']} XP", style: TextStyle(color: Colors.amber[800], fontWeight: FontWeight.bold, fontSize: 12)),
                    ),
                  ],
                ),
              ),
            );
          }),
        );
      },
    );
  }
}