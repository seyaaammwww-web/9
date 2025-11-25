import 'package:flutter/material.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:google_fonts/google_fonts.dart';

// استيراد الشاشات
import 'splash_screen.dart';
import 'login_screen.dart';
import 'student_dashboard.dart';
import 'teacher_dashboard.dart';

final ValueNotifier<ThemeMode> themeNotifier = ValueNotifier(ThemeMode.light);

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // 👇 التعديل: العودة للطريقة التلقائية (الأكثر استقراراً مع الإصدارات دي)
  try {
    await Firebase.initializeApp(); 
    print("✅ Firebase Connected Successfully");
  } catch (e) {
    print("❌ Firebase Error: $e");
  }

  runApp(YosrApp());
}

// ... باقي كود YosrApp كما هو بدون تغيير ...
class YosrApp extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<ThemeMode>(
      valueListenable: themeNotifier,
      builder: (_, mode, __) {
        return MaterialApp(
          debugShowCheckedModeBanner: false,
          title: 'منصتي - يُسر',
          themeMode: mode,
          locale: Locale('ar', 'AE'), 
          supportedLocales: [Locale('ar', 'AE'), Locale('en', 'US')],
          localizationsDelegates: [
            GlobalMaterialLocalizations.delegate,
            GlobalWidgetsLocalizations.delegate,
            GlobalCupertinoLocalizations.delegate,
          ],
          initialRoute: '/',
          routes: {
            '/': (context) => SplashScreen(),
            '/login': (context) => LoginScreen(),
            '/student_dashboard': (context) => StudentDashboard(),
            '/teacher_dashboard': (context) => TeacherDashboard(),
          },
          theme: ThemeData(
            brightness: Brightness.light,
            scaffoldBackgroundColor: Color(0xFFF5F7FA),
            primaryColor: Color(0xFF6C63FF),
            cardColor: Colors.white,
            textTheme: GoogleFonts.cairoTextTheme(ThemeData.light().textTheme),
            appBarTheme: AppBarTheme(
              backgroundColor: Colors.transparent,
              elevation: 0,
              centerTitle: true,
              iconTheme: IconThemeData(color: Colors.black87),
              titleTextStyle: GoogleFonts.cairo(color: Colors.black87, fontSize: 20, fontWeight: FontWeight.bold)
            ),
            useMaterial3: true,
          ),
          darkTheme: ThemeData(
            brightness: Brightness.dark,
            scaffoldBackgroundColor: Color(0xFF121212),
            primaryColor: Color(0xFF6C63FF),
            cardColor: Color(0xFF1E1E2C),
            textTheme: GoogleFonts.cairoTextTheme(ThemeData.dark().textTheme).apply(bodyColor: Colors.white, displayColor: Colors.white),
            useMaterial3: true,
          ),
        );
      },
    );
  }
}