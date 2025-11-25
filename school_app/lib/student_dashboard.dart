import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:intl/intl.dart';
import 'profile_settings_screen.dart'; 

import 'tabs/smart_study_tab.dart';
import 'tabs/courses_tab.dart';
import 'tabs/coding_lab_tab.dart';
import 'tabs/analytics_tab.dart';
import 'tabs/community_tab.dart';

class StudentDashboard extends StatefulWidget {
  @override
  _StudentDashboardState createState() => _StudentDashboardState();
}

class _StudentDashboardState extends State<StudentDashboard> {
  int _currentIndex = 0;
  final PageController _pageController = PageController(); // للتحكم في PageView
  final User? user = FirebaseAuth.instance.currentUser;
  DateTime? _lastPressedAt; // لتأكيد الخروج

  final List<Widget> _pages = [
    SmartStudyTab(),
    CoursesTab(),
    CodingLabTab(),
    CommunityTab(),
    AnalyticsTab(),
  ];

  @override
  void initState() {
    super.initState();
    _updateStreak();
  }

  @override
  void dispose() {
    _pageController.dispose();
    super.dispose();
  }

  Future<void> _updateStreak() async {
    final prefs = await SharedPreferences.getInstance();
    final today = DateFormat('yyyy-MM-dd').format(DateTime.now());
    final lastLogin = prefs.getString('last_login_date');
    int currentStreak = prefs.getInt('daily_streak') ?? 0;

    if (lastLogin != today) {
      if (lastLogin == DateFormat('yyyy-MM-dd').format(DateTime.now().subtract(Duration(days: 1)))) {
        currentStreak++;
      } else {
        currentStreak = 1;
      }
      await prefs.setString('last_login_date', today);
      await prefs.setInt('daily_streak', currentStreak);
    }
  }

  void _onPageChanged(int index) {
    setState(() => _currentIndex = index);
  }

  void _onNavItemTapped(int index) {
    _pageController.animateToPage(
      index, 
      duration: Duration(milliseconds: 300), 
      curve: Curves.easeInOut
    );
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false,
      onPopInvoked: (didPop) async {
        if (didPop) return;
        final now = DateTime.now();
        if (_lastPressedAt == null || now.difference(_lastPressedAt!) > Duration(seconds: 2)) {
          _lastPressedAt = now;
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text("اضغط مرة أخرى للخروج"),
            duration: Duration(seconds: 2),
            behavior: SnackBarBehavior.floating,
          ));
        } else {
          SystemNavigator.pop();
        }
      },
      child: Scaffold(
        extendBody: true, 
        appBar: _buildAppBar(),
        // استخدام PageView بدلاً من IndexedStack لدعم السحب
        body: PageView(
          controller: _pageController,
          onPageChanged: _onPageChanged,
          physics: BouncingScrollPhysics(), // تأثير سحب مرن
          children: _pages,
        ),
        bottomNavigationBar: _buildBottomNavBar(),
      ),
    );
  }

  PreferredSizeWidget _buildAppBar() {
    return AppBar(
      title: Row(
        children: [
          Container(
            padding: EdgeInsets.all(8),
            decoration: BoxDecoration(
              gradient: LinearGradient(colors: [Color(0xFF6C63FF), Color(0xFF4834D4)]),
              borderRadius: BorderRadius.circular(12),
              boxShadow: [BoxShadow(color: Color(0xFF6C63FF).withOpacity(0.3), blurRadius: 8, offset: Offset(0, 2))]
            ),
            child: Icon(Icons.code_rounded, color: Colors.white, size: 22),
          ),
          SizedBox(width: 12),
          Text("يُــــسر", style: TextStyle(fontWeight: FontWeight.w800, letterSpacing: 0.5)),
        ],
      ),
      actions: [
        StreamBuilder<DocumentSnapshot>(
          stream: FirebaseFirestore.instance.collection('users').doc(user?.uid).snapshots(),
          builder: (context, snapshot) {
            String? photoUrl;
            if (snapshot.hasData && snapshot.data!.exists) {
              var data = snapshot.data!.data() as Map<String, dynamic>;
              photoUrl = data.containsKey('photoUrl') ? data['photoUrl'] : null;
            }
            return GestureDetector(
              onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => ProfileSettingsScreen())),
              child: Container(
                margin: EdgeInsets.symmetric(horizontal: 15),
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  border: Border.all(color: Colors.grey.withOpacity(0.3), width: 1.5),
                  boxShadow: [BoxShadow(color: Colors.black12, blurRadius: 4)]
                ),
                child: CircleAvatar(
                  radius: 18,
                  backgroundColor: Colors.grey[200],
                  backgroundImage: photoUrl != null ? NetworkImage(photoUrl) : null,
                  child: photoUrl == null ? Icon(Icons.person, color: Colors.grey) : null,
                ),
              ),
            );
          },
        ),
      ],
    );
  }

  Widget _buildBottomNavBar() {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final bgColor = isDark ? Color(0xFF1E1E2C) : Colors.white;

    return Container(
      margin: EdgeInsets.fromLTRB(20, 0, 20, 25),
      padding: EdgeInsets.symmetric(vertical: 10, horizontal: 8),
      decoration: BoxDecoration(
        color: bgColor,
        borderRadius: BorderRadius.circular(30),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withOpacity(isDark ? 0.3 : 0.1), 
            blurRadius: 30, 
            offset: Offset(0, 10)
          )
        ],
        border: isDark ? Border.all(color: Colors.white10) : null,
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          _navItem(0, Icons.school_rounded, "ذاكر"),
          _navItem(1, Icons.rocket_launch_rounded, "مسارات"),
          _navItem(2, Icons.terminal_rounded, "محرر"),
          // إضافة شارة تنبيه (Badge) لتبويب المجتمع كمثال
          _navItem(3, Icons.chat_bubble_rounded, "مجتمع", showBadge: true),
          _navItem(4, Icons.analytics_rounded, "تحليل"),
        ],
      ),
    );
  }

  Widget _navItem(int index, IconData icon, String label, {bool showBadge = false}) {
    bool isSelected = _currentIndex == index;
    return GestureDetector(
      onTap: () => _onNavItemTapped(index),
      child: AnimatedContainer(
        duration: Duration(milliseconds: 300),
        curve: Curves.easeOut,
        padding: EdgeInsets.symmetric(horizontal: isSelected ? 12 : 10, vertical: 10),
        decoration: BoxDecoration(
          color: isSelected ? Color(0xFF6C63FF).withOpacity(0.15) : Colors.transparent,
          borderRadius: BorderRadius.circular(20),
        ),
        child: Stack(
          clipBehavior: Clip.none,
          children: [
            Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(
                  icon, 
                  color: isSelected ? Color(0xFF6C63FF) : Colors.grey, 
                  size: 26
                ),
                if (isSelected) ...[
                  SizedBox(height: 4),
                  Text(
                    label, 
                    style: TextStyle(
                      color: Color(0xFF6C63FF), 
                      fontWeight: FontWeight.bold, 
                      fontSize: 11
                    )
                  ),
                ]
              ],
            ),
            // عرض الشارة الحمراء إذا كانت مطلوبة وغير محددة
            if (showBadge && !isSelected)
              Positioned(
                top: -2,
                right: -2,
                child: Container(
                  width: 10,
                  height: 10,
                  decoration: BoxDecoration(
                    color: Colors.red,
                    shape: BoxShape.circle,
                    border: Border.all(color: Colors.white, width: 1.5)
                  ),
                ),
              )
          ],
        ),
      ),
    );
  }
}