import 'package:flutter/material.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:animate_do/animate_do.dart';
import '../chat_screen.dart';
import '../ai_analyzer_screen.dart';
import '../ai_roadmap_screen.dart';

class SmartStudyTab extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final user = FirebaseAuth.instance.currentUser;

    return StreamBuilder<DocumentSnapshot>(
      stream: FirebaseFirestore.instance.collection('users').doc(user?.uid).snapshots(),
      builder: (context, snapshot) {
        // قيم افتراضية في حال التحميل
        String name = "طالب مميز";
        int points = 0;

        if (snapshot.hasData && snapshot.data!.exists) {
          var data = snapshot.data!.data() as Map<String, dynamic>;
          name = data['name'] ?? "طالب مميز";
          points = data['totalPoints'] ?? 0;
        }

        return SingleChildScrollView(
          padding: EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // 1. بطاقة الترحيب والنقاط (الجزء الجديد)
              FadeInDown(
                child: Container(
                  width: double.infinity,
                  padding: EdgeInsets.all(25),
                  decoration: BoxDecoration(
                    gradient: LinearGradient(
                      colors: [Color(0xFF6C63FF), Color(0xFF4834D4)],
                      begin: Alignment.topLeft,
                      end: Alignment.bottomRight,
                    ),
                    borderRadius: BorderRadius.circular(25),
                    boxShadow: [
                      BoxShadow(
                        color: Color(0xFF6C63FF).withOpacity(0.3),
                        blurRadius: 15,
                        offset: Offset(0, 8),
                      ),
                    ],
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                "أهلاً بك،",
                                style: TextStyle(color: Colors.white70, fontSize: 14),
                              ),
                              SizedBox(height: 5),
                              Text(
                                name, // اسم الطالب المتغير
                                style: TextStyle(
                                  color: Colors.white,
                                  fontSize: 22,
                                  fontWeight: FontWeight.bold,
                                ),
                              ),
                            ],
                          ),
                          Container(
                            padding: EdgeInsets.all(10),
                            decoration: BoxDecoration(
                              color: Colors.white.withOpacity(0.2),
                              shape: BoxShape.circle,
                            ),
                            child: Icon(Icons.waving_hand_rounded, color: Colors.amber, size: 30),
                          ),
                        ],
                      ),
                      SizedBox(height: 20),
                      Container(
                        padding: EdgeInsets.symmetric(horizontal: 15, vertical: 10),
                        decoration: BoxDecoration(
                          color: Colors.black.withOpacity(0.2),
                          borderRadius: BorderRadius.circular(15),
                        ),
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Icon(Icons.stars_rounded, color: Colors.amber, size: 24),
                            SizedBox(width: 10),
                            Text(
                              "$points XP", // نقاط الطالب
                              style: TextStyle(
                                color: Colors.white,
                                fontSize: 18,
                                fontWeight: FontWeight.bold,
                              ),
                            ),
                            SizedBox(width: 8),
                            Text(
                              "مجموع نقاطك",
                              style: TextStyle(color: Colors.white70, fontSize: 12),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              
              SizedBox(height: 30),

              // 2. العنوان القديم
              FadeInDown(
                delay: Duration(milliseconds: 200),
                child: Text(
                  "أدوات الذكاء الاصطناعي 🤖", 
                  style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
                ),
              ),
              SizedBox(height: 5),
              FadeInDown(
                delay: Duration(milliseconds: 300),
                child: Text(
                  "اختر الأداة التي تناسب احتياجك الدراسي اليوم", 
                  style: TextStyle(color: Colors.grey[600]),
                ),
              ),
              SizedBox(height: 20),

              // 3. كروت الأدوات
              _buildToolCard(
                context,
                title: "المعلم الخاص (Chat)",
                desc: "اسأل عن أي درس واحصل على شرح فوري ومبسط.",
                icon: Icons.chat_bubble_outline_rounded,
                color: Colors.blue,
                page: ChatScreen(),
                delay: 400,
              ),
              
              _buildToolCard(
                context,
                title: "المحلل الذكي (PDF/Audio)",
                desc: "لخص الكتب والمحاضرات الصوتية واستخرج أسئلة منها.",
                icon: Icons.analytics_outlined,
                color: Colors.purple,
                page: AIAnalyzerScreen(type: AnalysisType.pdf),
                delay: 500,
              ),

              _buildToolCard(
                context,
                title: "راسم المسارات (Roadmap)",
                desc: "احصل على خطة دراسية زمنية مخصصة لأي مهارة.",
                icon: Icons.map_outlined,
                color: Colors.orange,
                page: AIRoadmapScreen(),
                delay: 600,
              ),
            ],
          ),
        );
      },
    );
  }

  Widget _buildToolCard(BuildContext context, {
    required String title, 
    required String desc, 
    required IconData icon, 
    required Color color, 
    required Widget page,
    required int delay,
  }) {
    return FadeInUp(
      duration: Duration(milliseconds: 500),
      delay: Duration(milliseconds: delay),
      child: GestureDetector(
        onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => page)),
        child: Container(
          margin: EdgeInsets.only(bottom: 20),
          padding: EdgeInsets.all(20),
          decoration: BoxDecoration(
            color: Theme.of(context).cardColor,
            borderRadius: BorderRadius.circular(20),
            boxShadow: [BoxShadow(color: color.withOpacity(0.1), blurRadius: 15, offset: Offset(0, 5))],
            border: Border.all(color: color.withOpacity(0.1)),
          ),
          child: Row(
            children: [
              Container(
                padding: EdgeInsets.all(15),
                decoration: BoxDecoration(
                  color: color.withOpacity(0.1),
                  borderRadius: BorderRadius.circular(15),
                ),
                child: Icon(icon, color: color, size: 30),
              ),
              SizedBox(width: 15),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title, style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
                    SizedBox(height: 5),
                    Text(desc, style: TextStyle(color: Colors.grey, fontSize: 12, height: 1.4)),
                  ],
                ),
              ),
              Icon(Icons.arrow_forward_ios_rounded, color: Colors.grey[300], size: 16)
            ],
          ),
        ),
      ),
    );
  }
}