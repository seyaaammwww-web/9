import 'dart:async';
import 'dart:math';
import 'package:flutter/material.dart';
import 'package:animate_do/animate_do.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_core/firebase_core.dart'; // ضروري للتحقق من التهيئة
import 'package:shared_preferences/shared_preferences.dart';

// استيراد الشاشات (تأكد من صحة المسارات)
import 'login_screen.dart';
import 'student_dashboard.dart';
import 'teacher_dashboard.dart';

// الإصدار الحالي للتطبيق
const String currentAppVersion = "1.0.0";

class SplashScreen extends StatefulWidget {
  @override
  _SplashScreenState createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen> {
  String _statusMessage = "جاري تجهيز بيئة التعلم...";
  String _quote = "";
  String? _userName;
  
  // حالات التطبيق
  bool _isMaintenance = false;
  bool _isUpdateRequired = false;
  bool _hasError = false; // حالة وجود خطأ لعرض زر إعادة المحاولة
  
  // Easter Egg
  int _logoTaps = 0;

  // ألوان التدرج والتحية
  List<Color> _bgColors = [Color(0xFF6C63FF), Color(0xFF4834D4)];
  String _greeting = "أهلاً بك";

  @override
  void initState() {
    super.initState();
    _setupTimeBasedTheme();
    _loadQuotes(); 
    _initializeApp();
  }

  void _setupTimeBasedTheme() {
    var hour = DateTime.now().hour;
    if (hour >= 5 && hour < 12) {
      _greeting = "صباح الخير ☀️";
      _bgColors = [Color(0xFFFF9966), Color(0xFFFF5E62)];
    } else if (hour >= 12 && hour < 17) {
      _greeting = "طاب يومك 🌤️";
      _bgColors = [Color(0xFF56CCF2), Color(0xFF2F80ED)];
    } else {
      _greeting = "مساء الخير 🌙";
      _bgColors = [Color(0xFF2E3192), Color(0xFF1BFFFF)];
    }
    if (mounted) setState(() {});
  }

  Future<void> _loadQuotes() async {
    const localQuotes = [
      "البرمجة هي فن التفكير بوضوح.",
      "لا يهم ببطء ما تمشي طالما أنك لا تتوقف.",
      "أفضل طريقة للتنبؤ بالمستقبل هي اختراعه.",
      "كل خبير كان يوماً ما مبتدئاً.",
      "التعليم هو السلاح الأقوى لتغيير العالم.",
    ];
    if (mounted) setState(() => _quote = localQuotes[Random().nextInt(localQuotes.length)]);
  }

  Future<void> _initializeApp() async {
    setState(() {
      _hasError = false;
      _statusMessage = "جاري الاتصال بالخدمات...";
    });

    final minDelay = Future.delayed(Duration(seconds: 3));

    try {
      // 👇 1. فحص الأمان: التأكد من أن Firebase يعمل
      if (Firebase.apps.isEmpty) {
        await Firebase.initializeApp();
      }

      // 2. بدء التحقق من البيانات
      final configCheck = _checkAppConfig();
      final userCheck = _checkUserSession();

      // انتظار الحد الأدنى من الوقت (للأنميشن)
      await minDelay;
      
      final config = await configCheck;
      
      if (config['maintenance'] == true) {
        if (mounted) setState(() => _isMaintenance = true);
        return;
      }

      String minVersion = config['min_version'] ?? "1.0.0";
      if (_isVersionOlder(currentAppVersion, minVersion)) {
        if (mounted) setState(() => _isUpdateRequired = true);
        return;
      }

      final nextScreen = await userCheck;
      if (mounted) {
        Navigator.pushReplacement(context, MaterialPageRoute(builder: (_) => nextScreen));
      }

    } catch (e) {
      // طباعة الخطأ في الكونسول للمطور
      print("SPLASH ERROR: $e");
      
      String errorMsg = "حدث خطأ في الاتصال.";
      if (e.toString().contains("no-app")) {
        errorMsg = "فشل تهيئة النظام (Firebase Error).";
      } else if (e.toString().contains("network")) {
        errorMsg = "يرجى التحقق من الإنترنت.";
      }

      if (mounted) {
        setState(() {
          _statusMessage = errorMsg;
          _hasError = true;
        });
      }
    }
  }

  bool _isVersionOlder(String current, String min) {
    return current.compareTo(min) < 0; 
  }

  Future<Map<String, dynamic>> _checkAppConfig() async {
    try {
      var doc = await FirebaseFirestore.instance.collection('app_settings').doc('config').get();
      if (doc.exists) return doc.data()!;
    } catch (e) {
      // تجاهل الأخطاء هنا واستخدام القيم الافتراضية
    }
    return {'maintenance': false, 'min_version': '1.0.0'};
  }

  Future<Widget> _checkUserSession() async {
    final prefs = await SharedPreferences.getInstance();
    bool isFirstTime = prefs.getBool('is_first_time') ?? true;

    if (isFirstTime) {
      await prefs.setBool('is_first_time', false);
      return OnboardingScreen();
    }

    User? user = FirebaseAuth.instance.currentUser;
    if (user != null) {
      try {
        var doc = await FirebaseFirestore.instance.collection('users').doc(user.uid).get();
        if (doc.exists) {
          if (mounted) {
            setState(() {
              _userName = doc.data()?['name']?.toString().split(' ')[0];
              _statusMessage = "مرحباً $_userName، جاري تحضير مكتبك...";
            });
          }
          await Future.delayed(Duration(seconds: 1));
          
          String role = doc.data()?['role'] ?? 'student';
          return role == 'teacher' ? TeacherDashboard() : StudentDashboard();
        }
      } catch (e) {
        // في حال فشل جلب البيانات، نذهب للداشبورد الافتراضي للطالب
         return StudentDashboard();
      }
    }
    return LoginScreen();
  }

  void _handleLogoTap() {
    _logoTaps++;
    if (_logoTaps == 5) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text("🚀 وضع المطور: تم تفعيل الأدوات المخفية!"),
          backgroundColor: Colors.green,
          behavior: SnackBarBehavior.floating,
        )
      );
      _logoTaps = 0;
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_isMaintenance) return _buildStateScreen(Icons.construction, "نحن في فترة صيانة", "نعود قريباً بشكل أفضل!", false);
    if (_isUpdateRequired) return _buildStateScreen(Icons.system_update, "تحديث مطلوب", "يرجى تحديث التطبيق للمتابعة.", true);

    return Scaffold(
      body: Container(
        width: double.infinity,
        height: double.infinity,
        decoration: BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: _bgColors,
          ),
        ),
        child: Center(
          child: SingleChildScrollView(
            padding: EdgeInsets.all(20),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                // 1. الشعار
                ZoomIn(
                  duration: Duration(milliseconds: 1000),
                  child: Semantics(
                    label: "شعار تطبيق يُسر",
                    button: true,
                    child: GestureDetector(
                      onTap: _handleLogoTap,
                      child: Container(
                        padding: EdgeInsets.all(30),
                        decoration: BoxDecoration(
                          color: Colors.white,
                          shape: BoxShape.circle,
                          boxShadow: [BoxShadow(color: Colors.black26, blurRadius: 20, offset: Offset(0, 10))],
                        ),
                        child: Icon(Icons.code_rounded, size: 70, color: _bgColors.first),
                      ),
                    ),
                  ),
                ),
                SizedBox(height: 30),
                
                // 2. اسم التطبيق
                FadeInUp(
                  duration: Duration(milliseconds: 1200),
                  child: Text(
                    "يُســر",
                    style: GoogleFonts.cairo(
                      fontSize: 50, fontWeight: FontWeight.w900, color: Colors.white, height: 1.0,
                      shadows: [Shadow(color: Colors.black38, blurRadius: 10, offset: Offset(0, 5))]
                    ),
                  ),
                ),
                SizedBox(height: 10),
                
                // 3. التحية
                FadeInUp(
                  delay: Duration(milliseconds: 500),
                  child: Text(
                    _userName != null ? "أهلاً بعودتك، $_userName! 👋" : _greeting,
                    style: GoogleFonts.tajawal(color: Colors.white, fontSize: 18, fontWeight: FontWeight.bold),
                  ),
                ),
                SizedBox(height: 40),

                // 4. الحالة والتحميل
                if (!_hasError)
                  SizedBox(
                    width: 150,
                    child: LinearProgressIndicator(backgroundColor: Colors.white24, color: Colors.white, minHeight: 2),
                  ),
                
                SizedBox(height: 15),
                Text(_statusMessage, style: TextStyle(color: Colors.white70, fontSize: 12)),
                
                // زر إعادة المحاولة يظهر فقط عند وجود خطأ
                if (_hasError)
                  Padding(
                    padding: const EdgeInsets.only(top: 20.0),
                    child: ElevatedButton.icon(
                      onPressed: _initializeApp,
                      icon: Icon(Icons.refresh),
                      label: Text("إعادة المحاولة"),
                      style: ElevatedButton.styleFrom(backgroundColor: Colors.white, foregroundColor: _bgColors.first),
                    ),
                  ),

                SizedBox(height: 50), 

                // 5. الاقتباس
                FadeInUp(
                  delay: Duration(milliseconds: 1500),
                  child: Container(
                    padding: EdgeInsets.symmetric(horizontal: 20, vertical: 10),
                    decoration: BoxDecoration(
                      color: Colors.white.withOpacity(0.1),
                      borderRadius: BorderRadius.circular(20),
                      border: Border.all(color: Colors.white12)
                    ),
                    child: Text(
                      "💡 \"$_quote\"",
                      textAlign: TextAlign.center,
                      style: GoogleFonts.tajawal(color: Colors.white.withOpacity(0.9), fontSize: 14, fontStyle: FontStyle.italic),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildStateScreen(IconData icon, String title, String desc, bool isUpdate) {
    return Scaffold(
      backgroundColor: Color(0xFF1E1E2C),
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(30.0),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(icon, size: 80, color: Colors.amber),
              SizedBox(height: 20),
              Text(title, style: TextStyle(color: Colors.white, fontSize: 24, fontWeight: FontWeight.bold)),
              SizedBox(height: 10),
              Text(desc, textAlign: TextAlign.center, style: TextStyle(color: Colors.grey)),
              SizedBox(height: 30),
              ElevatedButton(
                onPressed: () {
                  if (isUpdate) {
                    // رابط المتجر
                  } else {
                    setState(() { _isMaintenance = false; _isUpdateRequired = false; });
                    _initializeApp();
                  }
                },
                child: Text(isUpdate ? "تحديث الآن" : "تحقق مجدداً"),
              )
            ],
          ),
        ),
      ),
    );
  }
}

// Onboarding Screen
class OnboardingScreen extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Container(
        padding: EdgeInsets.all(30),
        decoration: BoxDecoration(
          gradient: LinearGradient(colors: [Color(0xFF6C63FF), Color(0xFF4834D4)], begin: Alignment.topLeft, end: Alignment.bottomRight)
        ),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            ZoomIn(child: Icon(Icons.rocket_launch_rounded, size: 100, color: Colors.white)),
            SizedBox(height: 30),
            FadeInUp(
              child: Text("مرحباً بك في يُسر!", style: TextStyle(fontSize: 30, fontWeight: FontWeight.bold, color: Colors.white)),
            ),
            SizedBox(height: 15),
            FadeInUp(
              delay: Duration(milliseconds: 200),
              child: Text("منصتك التعليمية الذكية. تعلم البرمجة، اختبر مهاراتك، وتواصل مع معلميك في مكان واحد.", 
                textAlign: TextAlign.center, style: TextStyle(color: Colors.white70, fontSize: 16, height: 1.5)),
            ),
            SizedBox(height: 50),
            FadeInUp(
              delay: Duration(milliseconds: 400),
              child: SizedBox(
                width: double.infinity,
                height: 55,
                child: ElevatedButton(
                  onPressed: () => Navigator.pushReplacement(context, MaterialPageRoute(builder: (_) => LoginScreen())),
                  child: Text("ابدأ رحلتك", style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                  style: ElevatedButton.styleFrom(backgroundColor: Colors.white, foregroundColor: Color(0xFF6C63FF), shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(15))),
                ),
              ),
            )
          ],
        ),
      ),
    );
  }
}