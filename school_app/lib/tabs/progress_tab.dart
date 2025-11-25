import 'package:flutter/material.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:animate_do/animate_do.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../achievements_screen.dart'; // للربط بصفحة الجوائز

class ProgressTab extends StatefulWidget {
  @override
  _ProgressTabState createState() => _ProgressTabState();
}

class _ProgressTabState extends State<ProgressTab> {
  int _streak = 0;

  @override
  void initState() {
    super.initState();
    _loadStreak();
  }

  void _loadStreak() async {
    final prefs = await SharedPreferences.getInstance();
    if (mounted) {
      setState(() => _streak = prefs.getInt('daily_streak') ?? 0);
    }
  }

  @override
  Widget build(BuildContext context) {
    final user = FirebaseAuth.instance.currentUser;
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final textColor = isDark ? Colors.white : Colors.black87;

    return StreamBuilder<DocumentSnapshot>(
      stream: FirebaseFirestore.instance.collection('users').doc(user!.uid).snapshots(),
      builder: (context, snapshot) {
        if (!snapshot.hasData || !snapshot.data!.exists) {
          return Center(child: CircularProgressIndicator(color: Color(0xFF6C63FF)));
        }
        
        var userData = snapshot.data!.data() as Map<String, dynamic>;
        int points = userData['totalPoints'] ?? 0;
        String name = userData['name'] ?? "المستخدم";
        
        // حساب التقدم نحو المستوى التالي (نفترض كل 500 نقطة مستوى)
        int currentLevel = (points / 500).floor();
        int nextMilestone = (currentLevel + 1) * 500;
        double progress = (points % 500) / 500; 

        return SingleChildScrollView(
          padding: const EdgeInsets.all(20.0),
          child: Column(
            children: [
              // 1. كارت الترحيب والـ Streak
              FadeInDown(
                child: Container(
                  width: double.infinity,
                  padding: EdgeInsets.all(25),
                  decoration: BoxDecoration(
                    gradient: LinearGradient(
                      colors: [Color(0xFF6C63FF), Color(0xFF8F94FB)],
                      begin: Alignment.topLeft,
                      end: Alignment.bottomRight,
                    ),
                    borderRadius: BorderRadius.circular(30),
                    boxShadow: [BoxShadow(color: Colors.indigo.withOpacity(0.3), blurRadius: 15, offset: Offset(0, 5))],
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          CircleAvatar(
                            radius: 30,
                            backgroundColor: Colors.white.withOpacity(0.2),
                            backgroundImage: userData['photoUrl'] != null ? NetworkImage(userData['photoUrl']) : null,
                            child: userData['photoUrl'] == null ? Icon(Icons.person, size: 35, color: Colors.white) : null,
                          ),
                          
                          // شريط الستريك مع زر الشرح (Tooltip)
                          Row(
                            children: [
                              Tooltip(
                                message: "أيام الدراسة المتتالية. تزيد يومياً عند تسجيل الدخول.",
                                child: Icon(Icons.info_outline, color: Colors.white70, size: 18),
                              ),
                              SizedBox(width: 8),
                              Container(
                                padding: EdgeInsets.symmetric(horizontal: 15, vertical: 8),
                                decoration: BoxDecoration(color: Colors.orange.withOpacity(0.9), borderRadius: BorderRadius.circular(20)),
                                child: Row(
                                  children: [
                                    Icon(Icons.local_fire_department, color: Colors.white, size: 20),
                                    SizedBox(width: 5),
                                    Text("$_streak أيام", style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
                                  ],
                                ),
                              ),
                            ],
                          )
                        ],
                      ),
                      SizedBox(height: 15),
                      Text("مرحباً، $name", style: TextStyle(color: Colors.white, fontSize: 22, fontWeight: FontWeight.bold)),
                      SizedBox(height: 5),
                      Text("المستوى الحالي: ${currentLevel + 1}", style: TextStyle(color: Colors.white70, fontSize: 14)),
                    ],
                  ),
                ),
              ),
              
              SizedBox(height: 40),

              // 2. دائرة التقدم و XP
              ZoomIn(
                child: Stack(
                  alignment: Alignment.center,
                  children: [
                    SizedBox(
                      width: 240, height: 240,
                      child: CircularProgressIndicator(value: 1.0, strokeWidth: 20, valueColor: AlwaysStoppedAnimation(isDark ? Colors.grey[800] : Colors.grey[100]), strokeCap: StrokeCap.round),
                    ),
                    SizedBox(
                      width: 240, height: 240,
                      child: CircularProgressIndicator(value: progress, strokeWidth: 20, backgroundColor: Colors.transparent, valueColor: AlwaysStoppedAnimation(Color(0xFF6C63FF)), strokeCap: StrokeCap.round),
                    ),
                    Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.bolt_rounded, size: 40, color: Colors.amber),
                        Text(points.toString(), style: GoogleFonts.changa(fontSize: 45, fontWeight: FontWeight.bold, color: textColor)),
                        Text("نقطة خبرة", style: TextStyle(color: Colors.grey)),
                        SizedBox(height: 5),
                        Text("الهدف التالي: $nextMilestone XP", style: TextStyle(color: Color(0xFF6C63FF), fontWeight: FontWeight.bold)),
                      ],
                    )
                  ],
                ),
              ),
              
              SizedBox(height: 40),

              // 3. زر عرض الإنجازات (Suggestions Fix)
              FadeInUp(
                child: SizedBox(
                  width: double.infinity,
                  height: 55,
                  child: ElevatedButton.icon(
                    onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => AchievementsScreen())),
                    icon: Icon(Icons.military_tech_rounded),
                    label: Text("عرض لوحة الإنجازات والأوسمة"),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.teal,
                      foregroundColor: Colors.white,
                      padding: EdgeInsets.symmetric(vertical: 15),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(15)),
                    ),
                  ),
                ),
              )
            ],
          ),
        );
      },
    );
  }
}