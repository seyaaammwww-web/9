import 'dart:math'; // ضروري جداً لحساب min في شريط التقدم
import 'package:flutter/material.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:animate_do/animate_do.dart';
import 'package:lottie/lottie.dart';

class AchievementsScreen extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final user = FirebaseAuth.instance.currentUser;

    return Scaffold(
      appBar: AppBar(title: Text("إنجازاتي"), centerTitle: true),
      body: StreamBuilder<DocumentSnapshot>(
        stream: FirebaseFirestore.instance.collection('users').doc(user?.uid).snapshots(),
        builder: (context, snapshot) {
          // --- بداية التعديل: التحقق من البيانات لمنع الكراش ---
          
          // 1. حالة التحميل
          if (snapshot.connectionState == ConnectionState.waiting) {
            return Center(child: CircularProgressIndicator());
          }

          // 2. حالة الخطأ
          if (snapshot.hasError) {
            return Center(child: Text("حدث خطأ في جلب البيانات"));
          }

          // 3. حالة عدم وجود مستند للمستخدم (مستخدم جديد)
          if (!snapshot.hasData || !snapshot.data!.exists) {
            return Center(child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(Icons.person_off, size: 50, color: Colors.grey),
                Text("لا يوجد سجل لهذا المستخدم بعد"),
              ],
            ));
          }
          // --- نهاية التعديل ---

          // قراءة البيانات بأمان الآن
          var data = snapshot.data!.data() as Map<String, dynamic>;
          int currentPoints = data['totalPoints'] ?? 0;

          // تحديد المستوى بناءً على النقاط
          String level = "مبتدئ";
          int nextMilestone = 100;
          
          if (currentPoints > 100) { level = "متوسط"; nextMilestone = 500; }
          if (currentPoints > 500) { level = "متقدم"; nextMilestone = 1000; }
          if (currentPoints > 1000) { level = "خبير"; nextMilestone = 2000; }

          // حساب نسبة التقدم (استخدام min لمنع تخطي 1.0)
          final double progress = nextMilestone > 0 ? min(1.0, currentPoints / nextMilestone) : 1.0;

          return SingleChildScrollView(
            padding: EdgeInsets.all(20),
            child: Column(
              children: [
                // كارت المستوى الرئيسي
                FadeInDown(
                  child: Container(
                    padding: EdgeInsets.all(20),
                    decoration: BoxDecoration(
                      gradient: LinearGradient(colors: [Color(0xFF6C63FF), Color(0xFF4834D4)]),
                      borderRadius: BorderRadius.circular(20),
                      boxShadow: [BoxShadow(color: Colors.indigo.withOpacity(0.3), blurRadius: 10, offset: Offset(0, 5))],
                    ),
                    child: Column(
                      children: [
                        // أيقونة الكأس أو المستوى (Lottie)
                        Lottie.network(
                          'https://assets10.lottiefiles.com/packages/lf20_touohxv0.json', 
                          height: 100, 
                          errorBuilder: (c,e,s) => Icon(Icons.emoji_events, size: 80, color: Colors.amber)
                        ),
                        SizedBox(height: 10),
                        Text("المستوى الحالي: $level", style: TextStyle(color: Colors.white, fontSize: 20, fontWeight: FontWeight.bold)),
                        SizedBox(height: 5),
                        Text("$currentPoints نقطة مكتسبة", style: TextStyle(color: Colors.white70)),
                        SizedBox(height: 20),
                        
                        // شريط التقدم
                        ClipRRect(
                          borderRadius: BorderRadius.circular(10),
                          child: LinearProgressIndicator(
                            value: progress,
                            backgroundColor: Colors.white24,
                            color: Colors.amber,
                            minHeight: 10,
                          ),
                        ),
                        SizedBox(height: 5),
                        Text("${(progress * 100).toInt()}% نحو المستوى التالي", style: TextStyle(color: Colors.white54, fontSize: 12)),
                      ],
                    ),
                  ),
                ),
                
                SizedBox(height: 30),
                Align(alignment: Alignment.centerRight, child: Text("الأوسمة المتاحة", style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold))),
                SizedBox(height: 15),

                // قائمة الأوسمة
                GridView.count(
                  shrinkWrap: true,
                  physics: NeverScrollableScrollPhysics(),
                  crossAxisCount: 3,
                  mainAxisSpacing: 10,
                  crossAxisSpacing: 10,
                  children: [
                    _buildBadge("بداية قوية", currentPoints >= 50, Icons.rocket_launch),
                    _buildBadge("متفاعل", currentPoints >= 200, Icons.local_fire_department),
                    _buildBadge("دافور", currentPoints >= 500, Icons.school),
                    _buildBadge("عبقري", currentPoints >= 1000, Icons.psychology),
                    _buildBadge("أسطورة", currentPoints >= 2000, Icons.emoji_events),
                    _buildBadge("اجتماعي", currentPoints >= 100, Icons.people),
                  ],
                )
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _buildBadge(String title, bool unlocked, IconData icon) {
    return FadeInUp(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Container(
            padding: EdgeInsets.all(15),
            decoration: BoxDecoration(
              color: unlocked ? Colors.amber.withOpacity(0.2) : Colors.grey[200],
              shape: BoxShape.circle,
              border: unlocked ? Border.all(color: Colors.amber, width: 2) : null,
            ),
            child: Icon(icon, color: unlocked ? Colors.amber[700] : Colors.grey, size: 30),
          ),
          SizedBox(height: 8),
          Text(title, style: TextStyle(fontSize: 12, color: unlocked ? Colors.black87 : Colors.grey), textAlign: TextAlign.center),
        ],
      ),
    );
  }
}