import 'package:flutter/material.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:animate_do/animate_do.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:intl/intl.dart' as intl; // لتنسيق التاريخ
import 'dart:async';

import 'login_screen.dart';
import 'main.dart'; 
import 'profile_settings_screen.dart';

// استيراد الصفحات الفرعية
import 'teacher_tabs/content_manager.dart'; 
import 'teacher_tabs/quiz_builder_hub.dart'; 
import 'teacher_tabs/students_analytics.dart'; 
import 'users_list_screen.dart';
import 'chat_screen.dart';

class TeacherDashboard extends StatefulWidget {
  @override
  _TeacherDashboardState createState() => _TeacherDashboardState();
}

class _TeacherDashboardState extends State<TeacherDashboard> {
  final User? user = FirebaseAuth.instance.currentUser;
  
  // حالة البيانات
  bool _isLoading = true;
  String _errorMessage = '';
  
  // بيانات المعلم
  String _teacherName = "";
  String? _photoUrl;
  
  // الإحصائيات
  Map<String, String> _stats = {
    'students': '-',
    'courses': '-',
    'rating': '-',
  };

  @override
  void initState() {
    super.initState();
    _fetchDashboardData();
  }

  Future<void> _fetchDashboardData() async {
    if (user == null) return;

    try {
      final results = await Future.wait([
        FirebaseFirestore.instance.collection('users').doc(user!.uid).get(),
        FirebaseFirestore.instance.collection('users').where('role', isEqualTo: 'student').count().get(),
        FirebaseFirestore.instance.collection('lessons').count().get(), // تعديل: عد الدروس الحقيقية
      ]);

      if (mounted) {
        final userDoc = results[0] as DocumentSnapshot<Map<String, dynamic>>;
        final studentsCount = (results[1] as AggregateQuerySnapshot).count;
        final coursesCount = (results[2] as AggregateQuerySnapshot).count;

        setState(() {
          _teacherName = userDoc.data()?['name'] ?? "معلم";
          _photoUrl = userDoc.data()?['photoUrl'];
          _stats['students'] = studentsCount.toString();
          _stats['courses'] = coursesCount.toString();
          _stats['rating'] = "5.0"; // تقييم ثابت للمعلم
          _isLoading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _isLoading = false;
          _errorMessage = "فشل تحميل بعض البيانات";
        });
      }
    }
  }

  void _confirmLogout() {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text("تسجيل الخروج"),
        content: Text("هل أنت متأكد أنك تريد المغادرة؟"),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: Text("إلغاء")),
          TextButton(
            onPressed: () async {
              Navigator.pop(ctx);
              await FirebaseAuth.instance.signOut();
              Navigator.pushReplacement(context, MaterialPageRoute(builder: (_) => LoginScreen()));
            },
            child: Text("خروج", style: TextStyle(color: Colors.red)),
          )
        ],
      ),
    );
  }

  void _showQuickActions() {
    showModalBottomSheet(
      context: context,
      backgroundColor: Colors.transparent,
      isScrollControlled: true,
      builder: (ctx) => _QuickActionsSheet(),
    );
  }

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final primaryColor = Color(0xFF6C63FF);

    return Scaffold(
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _showQuickActions,
        backgroundColor: primaryColor,
        elevation: 4,
        icon: Icon(Icons.add, color: Colors.white),
        label: Text("إنشاء سريع", style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
      ),
      body: CustomScrollView(
        slivers: [
          // 1. شريط التطبيق
          SliverAppBar(
            expandedHeight: 120,
            floating: true,
            pinned: true,
            backgroundColor: isDark ? Color(0xFF1E1E2C) : Colors.white,
            elevation: 0,
            leading: Padding(
              padding: const EdgeInsets.all(8.0),
              child: GestureDetector(
                onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => ProfileSettingsScreen())),
                child: CircleAvatar(
                  backgroundColor: Colors.grey[200],
                  backgroundImage: _photoUrl != null ? NetworkImage(_photoUrl!) : null,
                  child: _photoUrl == null ? Icon(Icons.person, color: Colors.grey) : null,
                ),
              ),
            ),
            actions: [
              // 🔥 تم التعديل: إزالة الشارة الحمراء الوهمية
              IconButton(
                icon: Icon(Icons.notifications_none_rounded, color: isDark ? Colors.white : Colors.black87),
                tooltip: "الإشعارات",
                onPressed: () {
                  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("لا توجد إشعارات جديدة حالياً")));
                },
              ),
              IconButton(
                icon: Icon(isDark ? Icons.light_mode : Icons.dark_mode, color: primaryColor),
                onPressed: () => themeNotifier.value = isDark ? ThemeMode.light : ThemeMode.dark,
              ),
              IconButton(
                icon: Icon(Icons.logout, color: Colors.redAccent),
                onPressed: _confirmLogout,
              )
            ],
            flexibleSpace: FlexibleSpaceBar(
              titlePadding: EdgeInsets.only(left: 20, right: 20, bottom: 15),
              title: _isLoading 
                ? SizedBox(width: 100, height: 10, child: LinearProgressIndicator(minHeight: 2)) 
                : Text(
                    "أهلاً، أ. $_teacherName",
                    style: GoogleFonts.cairo(
                      color: isDark ? Colors.white : Colors.black87,
                      fontSize: 16,
                      fontWeight: FontWeight.bold
                    ),
                  ),
            ),
          ),

          // 2. المحتوى الرئيسي
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.all(20.0),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // الإحصائيات
                  _isLoading 
                    ? _StatsSkeleton()
                    : FadeInDown(
                        child: Row(
                          children: [
                            Expanded(child: DashboardStatCard(title: "الطلاب", value: _stats['students']!, icon: Icons.groups, color: Colors.blue)),
                            SizedBox(width: 10),
                            Expanded(child: DashboardStatCard(title: "الدروس", value: _stats['courses']!, icon: Icons.video_library, color: Colors.purple)),
                            SizedBox(width: 10),
                            Expanded(child: DashboardStatCard(title: "التقييم", value: _stats['rating']!, icon: Icons.star, color: Colors.amber)),
                          ],
                        ),
                      ),
                  
                  SizedBox(height: 25),
                  
                  // المساعد الذكي
                  SmartAssistantCard(),

                  SizedBox(height: 25),
                  
                  // 🔥 تم التعديل: عرض النشاط الحقيقي بدلاً من الوهمي
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text("أحدث تسليمات الطلاب", style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                      Icon(Icons.history, size: 18, color: Colors.grey),
                    ],
                  ),
                  SizedBox(height: 10),
                  _RealRecentActivityList(), // استخدام الويدجت الجديدة الحقيقية

                  SizedBox(height: 25),
                  Text("لوحة التحكم", style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                  SizedBox(height: 15),

                  // شبكة الوصول السريع
                  GridView.count(
                    shrinkWrap: true,
                    physics: NeverScrollableScrollPhysics(),
                    crossAxisCount: 2,
                    crossAxisSpacing: 15,
                    mainAxisSpacing: 15,
                    children: [
                      AdminFeatureCard(title: "إدارة المحتوى", icon: Icons.folder_copy, color: Colors.blue, page: ContentManager(), tooltip: "رفع الفيديوهات والملفات"),
                      AdminFeatureCard(title: "بنك الأسئلة", icon: Icons.quiz, color: Colors.orange, page: QuizBuilderHub(), tooltip: "إنشاء وتعديل الاختبارات", badge: "هام"),
                      AdminFeatureCard(title: "تحليلات الطلاب", icon: Icons.pie_chart, color: Colors.teal, page: StudentsAnalytics(), tooltip: "متابعة الأداء والدرجات"),
                      AdminFeatureCard(title: "غرفة المعلمين", icon: Icons.forum, color: Colors.pink, page: UsersListScreen(), tooltip: "التواصل مع الطلاب والزملاء"),
                    ],
                  ),
                  SizedBox(height: 80),
                ],
              ),
            ),
          )
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// 🧩 المكونات الفرعية (Widgets)
// ---------------------------------------------------------------------------

class DashboardStatCard extends StatelessWidget {
  final String title;
  final String value;
  final IconData icon;
  final Color color;

  const DashboardStatCard({required this.title, required this.value, required this.icon, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: EdgeInsets.symmetric(vertical: 15),
      decoration: BoxDecoration(
        color: Theme.of(context).cardColor,
        borderRadius: BorderRadius.circular(15),
        border: Border.all(color: Colors.grey.withOpacity(0.1)),
        boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.02), blurRadius: 5)],
      ),
      child: Column(
        children: [
          Icon(icon, color: color, size: 24),
          SizedBox(height: 5),
          Text(value, style: TextStyle(fontWeight: FontWeight.bold, fontSize: 18)),
          Text(title, style: TextStyle(color: Colors.grey, fontSize: 12)),
        ],
      ),
    );
  }
}

class SmartAssistantCard extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return FadeInUp(
      child: Container(
        padding: EdgeInsets.all(20),
        decoration: BoxDecoration(
          gradient: LinearGradient(colors: [Color(0xFF6C63FF), Color(0xFF8F94FB)]),
          borderRadius: BorderRadius.circular(20),
          boxShadow: [BoxShadow(color: Color(0xFF6C63FF).withOpacity(0.3), blurRadius: 10, offset: Offset(0, 5))],
        ),
        child: Column(
          children: [
            Row(
              children: [
                Icon(Icons.auto_awesome, color: Colors.white, size: 24),
                SizedBox(width: 10),
                Text("المساعد الذكي", style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 16)),
              ],
            ),
            SizedBox(height: 15),
            Text("بم يمكنني مساعدتك اليوم؟", style: TextStyle(color: Colors.white70)),
            SizedBox(height: 15),
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(
                children: [
                  _ActionChip(label: "⚡ خطط لدرس", prompt: "خطة درس عن..."),
                  _ActionChip(label: "📝 أسئلة اختبار", prompt: "أسئلة عن..."),
                  _ActionChip(label: "💡 أفكار نشاط", prompt: "نشاط تفاعلي..."),
                ],
              ),
            )
          ],
        ),
      ),
    );
  }
}

class _ActionChip extends StatelessWidget {
  final String label;
  final String prompt;

  const _ActionChip({required this.label, required this.prompt});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(left: 8.0),
      child: ActionChip(
        label: Text(label),
        backgroundColor: Colors.white,
        labelStyle: TextStyle(color: Color(0xFF6C63FF), fontWeight: FontWeight.bold, fontSize: 12),
        elevation: 2,
        padding: EdgeInsets.symmetric(horizontal: 5, vertical: 8),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20), side: BorderSide.none),
        onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => ChatScreen(title: "المساعد الذكي", sysPrompt: "أنت مساعد خبير للمعلمين."))),
      ),
    );
  }
}

// 🔥🔥 الويدجت الجديدة التي تعرض النشاط الحقيقي 🔥🔥
class _RealRecentActivityList extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    // الاستماع لمجموعة نتائج الاختبارات، مرتبة حسب الأحدث
    return StreamBuilder<QuerySnapshot>(
      stream: FirebaseFirestore.instance
          .collection('quiz_results')
          .orderBy('timestamp', descending: true)
          .limit(5) // عرض آخر 5 أنشطة فقط
          .snapshots(),
      builder: (context, snapshot) {
        if (snapshot.connectionState == ConnectionState.waiting) {
          return Center(child: LinearProgressIndicator());
        }

        if (!snapshot.hasData || snapshot.data!.docs.isEmpty) {
          return Container(
            padding: EdgeInsets.all(20),
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: Theme.of(context).cardColor,
              borderRadius: BorderRadius.circular(15),
              border: Border.all(color: Colors.grey.withOpacity(0.2))
            ),
            child: Text("لا يوجد نشاط للطلاب حتى الآن", style: TextStyle(color: Colors.grey)),
          );
        }

        var docs = snapshot.data!.docs;

        return Column(
          children: docs.map((doc) {
            var data = doc.data() as Map<String, dynamic>;
            String studentId = data['studentId'];
            
            // نحتاج لجلب اسم الطالب بناءً على الـ ID لأنه غير مخزن في النتيجة
            return FutureBuilder<DocumentSnapshot>(
              future: FirebaseFirestore.instance.collection('users').doc(studentId).get(),
              builder: (context, userSnapshot) {
                String studentName = "طالب";
                if (userSnapshot.hasData && userSnapshot.data!.exists) {
                  studentName = userSnapshot.data!['name'] ?? "طالب";
                }

                // تنسيق الوقت
                String timeStr = "";
                if (data['timestamp'] != null) {
                  DateTime date = (data['timestamp'] as Timestamp).toDate();
                  timeStr = intl.DateFormat('hh:mm a', 'ar').format(date);
                }

                return Container(
                  margin: EdgeInsets.only(bottom: 8),
                  padding: EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: Theme.of(context).cardColor,
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: Colors.grey.withOpacity(0.1))
                  ),
                  child: Row(
                    children: [
                      CircleAvatar(
                        radius: 18,
                        backgroundColor: Colors.green.withOpacity(0.1),
                        child: Icon(Icons.check_circle, color: Colors.green, size: 18),
                      ),
                      SizedBox(width: 10),
                      Expanded(
                        child: RichText(
                          text: TextSpan(
                            style: TextStyle(color: Theme.of(context).textTheme.bodyMedium?.color, fontFamily: 'Cairo', fontSize: 13),
                            children: [
                              TextSpan(text: "أنهى "),
                              TextSpan(text: studentName, style: TextStyle(fontWeight: FontWeight.bold, color: Color(0xFF6C63FF))),
                              TextSpan(text: " اختبار "),
                              TextSpan(text: "${data['quizTitle']}", style: TextStyle(fontWeight: FontWeight.bold)),
                              TextSpan(text: " بنتيجة ${data['score']}"),
                            ]
                          ),
                        ),
                      ),
                      Text(timeStr, style: TextStyle(fontSize: 10, color: Colors.grey)),
                    ],
                  ),
                );
              },
            );
          }).toList(),
        );
      },
    );
  }
}

class AdminFeatureCard extends StatelessWidget {
  final String title;
  final IconData icon;
  final Color color;
  final Widget page;
  final String tooltip;
  final String? badge;

  const AdminFeatureCard({required this.title, required this.icon, required this.color, required this.page, required this.tooltip, this.badge});

  @override
  Widget build(BuildContext context) {
    return FadeInUp(
      child: Tooltip(
        message: tooltip,
        child: InkWell(
          onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => page)),
          borderRadius: BorderRadius.circular(20),
          child: Stack(
            children: [
              Container(
                width: double.infinity,
                decoration: BoxDecoration(
                  color: Theme.of(context).cardColor,
                  borderRadius: BorderRadius.circular(20),
                  boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 10, offset: Offset(0, 5))],
                ),
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Container(
                      padding: EdgeInsets.all(12),
                      decoration: BoxDecoration(color: color.withOpacity(0.1), shape: BoxShape.circle),
                      child: Icon(icon, color: color, size: 30),
                    ),
                    SizedBox(height: 12),
                    Text(title, style: TextStyle(fontWeight: FontWeight.bold, fontSize: 14)),
                  ],
                ),
              ),
              if (badge != null)
                Positioned(
                  top: 10, left: 10,
                  child: Container(
                    padding: EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                    decoration: BoxDecoration(color: Colors.red[100], borderRadius: BorderRadius.circular(5)),
                    child: Text(badge!, style: TextStyle(fontSize: 10, color: Colors.red, fontWeight: FontWeight.bold)),
                  ),
                )
            ],
          ),
        ),
      ),
    );
  }
}

class _QuickActionsSheet extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Container(
      padding: EdgeInsets.all(25),
      decoration: BoxDecoration(
        color: Theme.of(context).cardColor,
        borderRadius: BorderRadius.vertical(top: Radius.circular(25)),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(width: 40, height: 4, decoration: BoxDecoration(color: Colors.grey[300], borderRadius: BorderRadius.circular(10))),
          SizedBox(height: 20),
          Text("ماذا تريد أن تنشئ؟", style: TextStyle(fontWeight: FontWeight.bold, fontSize: 18)),
          SizedBox(height: 25),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceAround,
            children: [
              _QuickActionItem(icon: Icons.quiz, label: "اختبار جديد", color: Colors.orange, onTap: () {
                 Navigator.pop(context);
                 Navigator.push(context, MaterialPageRoute(builder: (_) => QuizBuilderHub()));
              }),
              _QuickActionItem(icon: Icons.video_call, label: "درس جديد", color: Colors.blue, onTap: () {
                 Navigator.pop(context);
                 Navigator.push(context, MaterialPageRoute(builder: (_) => ContentManager()));
              }),
              _QuickActionItem(icon: Icons.campaign, label: "إعلان هام", color: Colors.red, onTap: () {
                 Navigator.pop(context);
                 // توجيه إلى صفحة إدارة الفصل لكتابة الإعلان
                 ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("توجه لإدارة الفصل لكتابة الإعلان")));
              }),
            ],
          ),
          SizedBox(height: 20),
        ],
      ),
    );
  }
}

class _QuickActionItem extends StatelessWidget {
  final IconData icon;
  final String label;
  final Color color;
  final VoidCallback onTap;

  const _QuickActionItem({required this.icon, required this.label, required this.color, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(15),
      child: Container(
        padding: EdgeInsets.symmetric(horizontal: 10, vertical: 15),
        child: Column(
          children: [
            Container(
              padding: EdgeInsets.all(15),
              decoration: BoxDecoration(color: color.withOpacity(0.1), shape: BoxShape.circle),
              child: Icon(icon, color: color, size: 28),
            ),
            SizedBox(height: 8),
            Text(label, style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold)),
          ],
        ),
      ),
    );
  }
}

class _StatsSkeleton extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Row(
      children: List.generate(3, (index) => Expanded(
        child: Container(
          height: 100,
          margin: EdgeInsets.symmetric(horizontal: 5),
          decoration: BoxDecoration(color: Colors.grey[200], borderRadius: BorderRadius.circular(15)),
        ),
      )),
    );
  }
}