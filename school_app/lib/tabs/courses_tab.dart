import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:google_generative_ai/google_generative_ai.dart';
import 'package:animate_do/animate_do.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:intl/intl.dart';
import '../certificate_screen.dart'; 

// ---------------------------------------------------------------------------
// 📦 كلاس البيانات (تمت إضافة حقل details للوصف المطول)
// ---------------------------------------------------------------------------
class _CourseData {
  final String id;
  final String title;
  final String instructor;
  final String url;
  final String category;
  final Color color;
  final String shortDescription; // نبذة مختصرة للكروت الخارجية
  final String details; // 🔥 نبذة مطولة للتفاصيل الداخلية
  final double rating;

  _CourseData(this.id, this.title, this.instructor, this.url, this.category, this.color, this.shortDescription, this.details, {this.rating = 4.8});
}

class CoursesTab extends StatefulWidget {
  @override
  _CoursesTabState createState() => _CoursesTabState();
}

class _CoursesTabState extends State<CoursesTab> {
  final String apiKey = 'AIzaSyAP5WCqlWMylEUAjrCG8tn7KRE1kQd4mwE';
  bool _isLoadingQuest = false;
  
  String _searchQuery = "";
  String _selectedFilter = "الكل";
  List<String> _bookmarkedIds = [];
  String _lastPlayedCourseId = "";
  
  final TextEditingController _searchController = TextEditingController();

  // --- البيانات (تم تحديث النصوص لتكون مطولة وواقعية) ---
  final List<_CourseData> _staticCourses = [
    _CourseData(
      "flutter_wael", 
      "Flutter الكامل", 
      "م. وائل أبو حمزة", 
      "https://youtube.com/playlist?list=PLw6Y5u47CYq47oDw63bMqkq06fjuoK_GJ", 
      "mobile", Colors.blue, 
      "المرجع العربي الأقوى لتعلم Flutter من الصفر.",
      "هذا المسار التدريبي هو دليلك الشامل لاحتراف تطوير تطبيقات الموبايل باستخدام Flutter. ستبدأ رحلتك بتعلم لغة Dart بعمق، ثم تنتقل إلى أساسيات Flutter وكيفية بناء واجهات المستخدم (UI) بشكل احترافي. يغطي الكورس أيضاً إدارة الحالة (State Management) والتعامل مع الـ API وقواعد البيانات، مما يؤهلك لسوق العمل بقوة."
    ),
    _CourseData(
      "android_kotlin", 
      "Android Native (Kotlin)", 
      "م. محمد إبراهيم", 
      "https://youtube.com/playlist?list=PLlxmoA0rQ-Lw5k_QCqVl3rsoJOnb_00UV", 
      "mobile", Colors.green, 
      "دورة شاملة لتطوير تطبيقات الأندرويد بلغة Kotlin.",
      "تعلم برمجة تطبيقات الأندرويد الأصلية (Native) باستخدام اللغة الرسمية من جوجل: Kotlin. ستتعرف على بيئة Android Studio، دورة حياة التطبيق، كيفية تصميم الشاشات بـ XML و Jetpack Compose، والتعامل مع الخدمات الخلفية. كورس مثالي لمن يريد التخصص العميق في نظام أندرويد."
    ),
    _CourseData(
      "web_nour", 
      "تأسيس الويب (HTML/CSS)", 
      "Nour Homsi", 
      "https://youtube.com/playlist?list=PLU0wE7dsJI8QWlkQphNZXMICIDo6u5IWR", 
      "web", Colors.orange, 
      "البداية الصحيحة لأي مطور ويب. تعلم الهيكلة والتنسيق.",
      "لا يمكن أن تصبح مطور ويب بدون أساس قوي. في هذا الكورس، ستتعلم كيف تبني هيكل صفحات الويب باستخدام HTML5 وكيف تجعلها تبدو رائعة ومتجاوبة مع جميع الشاشات باستخدام CSS3. الشرح مبسط وعملي جداً للمبتدئين."
    ),
    _CourseData(
      "js_elzero", 
      "JavaScript الأساسيات", 
      "Elzero Web School", 
      "https://youtube.com/playlist?list=PLknwEmKsW8OuTqUDaFRBiAViDZ5uI3VcE", 
      "web", Colors.amber, 
      "أعمق شرح عربي للغة جافاسكريبت.",
      "جافاسكريبت هي روح الويب الحديث. يقدم المهندس أسامة الزيرو شرحاً تفصيلاً لكل صغيرة وكبيرة في اللغة، بدءاً من المتغيرات والدوال، وصولاً إلى التعامل مع DOM والأحداث (Events) والبرمجة الكائنية. هذا الكورس هو حجر الأساس لأي إطار عمل ستتعلمه لاحقاً."
    ),
    _CourseData(
      "python_elzero", 
      "Python (من الصفر)", 
      "Elzero Web School", 
      "https://youtube.com/playlist?list=PLDoPjvoNmBAyE_gei5d18qkfIe-Z8mocs", 
      "ai", Colors.purple, 
      "تعلم بايثون، لغة العصر، من الصفر وحتى الاحتراف.",
      "بايثون هي اللغة الأكثر طلباً حالياً في مجالات الذكاء الاصطناعي وتحليل البيانات. ستتعلم في هذا الكورس أساسيات البرمجة ببايثون، التعامل مع الملفات، قواعد البيانات، والمكتبات الأساسية. الشرح ممتع وسلس ويناسب جميع المستويات."
    ),
  ];

  @override
  void initState() {
    super.initState();
    _loadUserData();
  }

  Future<void> _loadUserData() async {
    final prefs = await SharedPreferences.getInstance();
    setState(() {
      _bookmarkedIds = prefs.getStringList('bookmarked_courses') ?? [];
      _lastPlayedCourseId = prefs.getString('last_played_course_id') ?? "";
    });
  }

  Future<void> _toggleBookmark(String courseId) async {
    final prefs = await SharedPreferences.getInstance();
    setState(() {
      if (_bookmarkedIds.contains(courseId)) {
        _bookmarkedIds.remove(courseId);
      } else {
        _bookmarkedIds.add(courseId);
      }
    });
    await prefs.setStringList('bookmarked_courses', _bookmarkedIds);
  }

  // --- Generative AI Quest Logic ---
  Future<void> _startDailyQuest(BuildContext context) async {
    final prefs = await SharedPreferences.getInstance();
    final String todayDate = DateFormat('yyyy-MM-dd').format(DateTime.now());
    
    if (prefs.getString('last_daily_quest_date') == todayDate) {
      _showAlreadyPlayedDialog(context);
      return;
    }

    setState(() => _isLoadingQuest = true);
    try {
      final model = GenerativeModel(model: 'gemini-2.5-pro', apiKey: apiKey);
      final prompt = """
      Generate one challenging programming MCQ in Arabic (JSON format).
      Format: { "question": "...", "options": ["..."], "correct_index": 0, "explanation": "..." }
      Topic: Software Engineering.
      """;
      final response = await model.generateContent([Content.text(prompt)]);
      String jsonText = response.text?.replaceAll('```json', '').replaceAll('```', '').trim() ?? "{}";
      if(jsonText.indexOf('{') != -1) jsonText = jsonText.substring(jsonText.indexOf('{'), jsonText.lastIndexOf('}') + 1);

      Map<String, dynamic> questData = jsonDecode(jsonText);
      if (questData.containsKey('question')) {
        _showQuestDialog(context, questData);
      }
    } catch (e) {
      _showQuestDialog(context, {
        "question": "ما هو التعقيد الزمني للبحث الثنائي (Binary Search)؟",
        "options": ["O(n)", "O(log n)", "O(n^2)", "O(1)"],
        "correct_index": 1,
        "explanation": "لأننا نقسم مساحة البحث إلى النصف في كل خطوة."
      });
    } finally {
      setState(() => _isLoadingQuest = false);
    }
  }

  void _showAlreadyPlayedDialog(BuildContext context) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Row(children: [Icon(Icons.check_circle, color: Colors.green), SizedBox(width: 10), Text("تمت المهمة!")]),
        content: Text("لقد حصلت على نقاط اليوم. عد غداً لزيادة الـ Streak الخاص بك!"),
        actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: Text("حسناً"))],
      ),
    );
  }

  void _showQuestDialog(BuildContext context, Map<String, dynamic> data) {
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => _QuestDialogUI(
        question: data['question'],
        options: List<String>.from(data['options']),
        correctIndex: data['correct_index'],
        explanation: data['explanation'] ?? "",
        onSuccess: () {
           final user = FirebaseAuth.instance.currentUser;
           if (user != null) FirebaseFirestore.instance.collection('users').doc(user.uid).update({'totalPoints': FieldValue.increment(50)});
        },
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final bgColor = isDark ? Color(0xFF121212) : Color(0xFFF5F7FA);

    return Scaffold(
      backgroundColor: bgColor,
      body: StreamBuilder<QuerySnapshot>(
        stream: FirebaseFirestore.instance.collection('lessons').orderBy('createdAt', descending: true).snapshots(),
        builder: (context, snapshot) {
          List<_CourseData> allCourses = List.from(_staticCourses);
          if (snapshot.hasData) {
            for (var doc in snapshot.data!.docs) {
              var data = doc.data() as Map<String, dynamic>;
               allCourses.insert(0, _CourseData(
                 doc.id,
                 data['title'] ?? "كورس إضافي", 
                 "المعلم", 
                 data['link'] ?? "", 
                 data['category'] ?? "other", 
                 Colors.teal,
                 data['description'] ?? "تمت إضافته حديثاً",
                 data['details'] ?? "لا يوجد وصف تفصيلي لهذا الكورس.", // التعامل مع البيانات الجديدة
                 rating: 5.0
               ));
            }
          }

          var filteredCourses = allCourses.where((c) {
            bool matchSearch = _searchQuery.isEmpty || c.title.toLowerCase().contains(_searchQuery.toLowerCase());
            bool matchFilter = _selectedFilter == "الكل" ||
                               (_selectedFilter == "المفضلة" && _bookmarkedIds.contains(c.id)) ||
                               (_selectedFilter == "موبايل" && c.category == "mobile") ||
                               (_selectedFilter == "ويب" && c.category == "web") ||
                               (_selectedFilter == "ذكاء اصطناعي" && c.category == "ai");
            return matchSearch && matchFilter;
          }).toList();

          return CustomScrollView(
            physics: BouncingScrollPhysics(),
            slivers: [
              // --- 1. شريط العنوان والبحث (تم الإصلاح: زيادة الارتفاع) ---
              SliverAppBar(
                backgroundColor: isDark ? Color(0xFF1E1E2C) : Colors.white,
                floating: true,
                pinned: true,
                snap: false,
                expandedHeight: 220, // 🔥 تم زيادة الارتفاع لمنع التداخل
                elevation: 0,
                flexibleSpace: FlexibleSpaceBar(
                  background: Padding(
                    padding: const EdgeInsets.fromLTRB(20, 60, 20, 80), // 🔥 مسافة سفلية كبيرة للابتعاد عن البحث
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text("أكاديمية يُــسر", style: TextStyle(fontSize: 28, fontWeight: FontWeight.bold, color: Color(0xFF6C63FF))),
                                SizedBox(height: 5),
                                Text("اكتشف شغفك وابدأ رحلة التعلم", style: TextStyle(color: Colors.grey, fontSize: 14)),
                              ],
                            ),
                            CircleAvatar(
                              radius: 25,
                              backgroundColor: Color(0xFF6C63FF).withOpacity(0.1), 
                              child: Icon(Icons.school_rounded, color: Color(0xFF6C63FF), size: 30)
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ),
                bottom: PreferredSize(
                  preferredSize: Size.fromHeight(70),
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(20, 0, 20, 15),
                    child: Container(
                      decoration: BoxDecoration(
                        color: isDark ? Colors.grey[800] : Colors.grey[100],
                        borderRadius: BorderRadius.circular(15),
                        boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 10, offset: Offset(0, 5))]
                      ),
                      child: TextField(
                        controller: _searchController,
                        onChanged: (val) => setState(() => _searchQuery = val),
                        decoration: InputDecoration(
                          hintText: "ابحث عن كورس، مهارة، أو مدرب...",
                          prefixIcon: Icon(Icons.search, color: Color(0xFF6C63FF)),
                          border: InputBorder.none,
                          contentPadding: EdgeInsets.symmetric(horizontal: 20, vertical: 15),
                        ),
                      ),
                    ),
                  ),
                ),
              ),

              // --- 2. المحتوى (Content) ---
              SliverToBoxAdapter(
                child: Padding(
                  padding: EdgeInsets.fromLTRB(16, 20, 16, 100),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      // بانر التحدي
                      _buildDailyQuestBanner(),
                      SizedBox(height: 25),
                      
                      // الفلاتر
                      SingleChildScrollView(
                        scrollDirection: Axis.horizontal,
                        physics: BouncingScrollPhysics(),
                        child: Row(
                          children: ["الكل", "المفضلة", "موبايل", "ويب", "ذكاء اصطناعي"]
                              .map((f) => _buildFilterChip(f)).toList(),
                        ),
                      ),
                      SizedBox(height: 25),
                      
                      // قائمة الكورسات
                      if (filteredCourses.isEmpty)
                        Center(child: Padding(
                          padding: const EdgeInsets.only(top: 50),
                          child: Column(
                            children: [
                              Icon(Icons.search_off, size: 60, color: Colors.grey[300]),
                              SizedBox(height: 10),
                              Text("لم يتم العثور على نتائج", style: TextStyle(color: Colors.grey)),
                            ],
                          ),
                        ))
                      else
                        ListView.separated(
                          shrinkWrap: true,
                          physics: NeverScrollableScrollPhysics(),
                          itemCount: filteredCourses.length,
                          separatorBuilder: (ctx, i) => SizedBox(height: 20),
                          itemBuilder: (ctx, i) => _buildBeautifulCourseCard(context, filteredCourses[i]),
                        ),
                    ],
                  ),
                ),
              )
            ],
          );
        },
      ),
    );
  }

  // الكارت الخارجي (كما هو بالتصميم القديم المحبب)
  Widget _buildBeautifulCourseCard(BuildContext context, _CourseData course) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final isBookmarked = _bookmarkedIds.contains(course.id);
    final bool isLastPlayed = _lastPlayedCourseId == course.id;

    IconData categoryIcon;
    switch(course.category) {
      case "mobile": categoryIcon = Icons.phone_android_rounded; break;
      case "web": categoryIcon = Icons.language_rounded; break;
      case "ai": categoryIcon = Icons.psychology_rounded; break;
      default: categoryIcon = Icons.code_rounded;
    }

    return FadeInUp(
      duration: Duration(milliseconds: 300),
      child: GestureDetector(
        onTap: () async {
          final prefs = await SharedPreferences.getInstance();
          prefs.setString('last_played_course_id', course.id);
          setState(() => _lastPlayedCourseId = course.id);
          Navigator.push(context, MaterialPageRoute(builder: (_) => CourseDetailsScreen(course: course)));
        },
        child: Container(
          decoration: BoxDecoration(
            color: isDark ? Color(0xFF252530) : Colors.white,
            borderRadius: BorderRadius.circular(20),
            boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 15, offset: Offset(0, 8))],
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Stack(
                children: [
                  ClipRRect(
                    borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
                    child: Container(
                      height: 160, 
                      width: double.infinity,
                      decoration: BoxDecoration(
                        gradient: LinearGradient(
                          colors: [course.color, course.color.withOpacity(0.7)],
                          begin: Alignment.topLeft,
                          end: Alignment.bottomRight,
                        ),
                      ),
                      child: Stack(
                        children: [
                          Positioned(
                            right: -30, bottom: -30,
                            child: Transform.rotate(
                              angle: -0.2,
                              child: Icon(categoryIcon, size: 160, color: Colors.white.withOpacity(0.15)),
                            ),
                          ),
                          Center(
                            child: Container(
                              padding: EdgeInsets.all(12),
                              decoration: BoxDecoration(
                                color: Colors.white.withOpacity(0.2),
                                shape: BoxShape.circle,
                                border: Border.all(color: Colors.white.withOpacity(0.6), width: 1.5),
                                boxShadow: [BoxShadow(color: Colors.black12, blurRadius: 8)]
                              ),
                              child: Icon(Icons.play_arrow_rounded, color: Colors.white, size: 40),
                            ),
                          ),
                          Positioned(
                            bottom: 0, left: 0, right: 0,
                            child: Container(
                              height: 60,
                              decoration: BoxDecoration(gradient: LinearGradient(begin: Alignment.bottomCenter, end: Alignment.topCenter, colors: [Colors.black.withOpacity(0.6), Colors.transparent])),
                            ),
                          ),
                          Positioned(
                            bottom: 12, right: 15, left: 15,
                            child: Text(course.title, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.bold, shadows: [Shadow(color: Colors.black38, blurRadius: 4)])),
                          ),
                        ],
                      ),
                    ),
                  ),
                  if (isLastPlayed)
                    Positioned(
                      top: 12, left: 12,
                      child: Container(
                        padding: EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                        decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(12), boxShadow: [BoxShadow(color: Colors.black12, blurRadius: 4)]),
                        child: Row(children: [Icon(Icons.history, size: 12, color: Color(0xFF6C63FF)), SizedBox(width: 4), Text("تابع المشاهدة", style: TextStyle(color: Color(0xFF6C63FF), fontSize: 10, fontWeight: FontWeight.bold))]),
                      ),
                    ),
                ],
              ),
              Padding(
                padding: const EdgeInsets.all(15.0),
                child: Column(
                  children: [
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Row(
                          children: [
                            CircleAvatar(radius: 14, backgroundColor: Colors.grey[100], child: Icon(Icons.person, size: 16, color: Colors.grey[600])),
                            SizedBox(width: 8),
                            Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(course.instructor, style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: isDark ? Colors.white70 : Colors.black87)),
                                Row(children: [Icon(Icons.star_rounded, size: 14, color: Colors.amber), Text(" ${course.rating}", style: TextStyle(fontSize: 11, color: Colors.grey, fontWeight: FontWeight.bold))])
                              ],
                            ),
                          ],
                        ),
                        InkWell(
                          onTap: () => _toggleBookmark(course.id),
                          borderRadius: BorderRadius.circular(50),
                          child: Container(
                            padding: EdgeInsets.all(8),
                            decoration: BoxDecoration(color: isBookmarked ? Color(0xFF6C63FF).withOpacity(0.1) : Colors.grey.withOpacity(0.05), shape: BoxShape.circle),
                            child: Icon(isBookmarked ? Icons.bookmark : Icons.bookmark_border_rounded, color: isBookmarked ? Color(0xFF6C63FF) : Colors.grey, size: 22),
                          ),
                        )
                      ],
                    ),
                  ],
                ),
              )
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildDailyQuestBanner() {
    return FadeInDown(
      child: InkWell(
        onTap: _isLoadingQuest ? null : () => _startDailyQuest(context),
        child: Container(
          padding: EdgeInsets.all(20),
          decoration: BoxDecoration(
            gradient: LinearGradient(colors: [Color(0xFF6C63FF), Color(0xFF8F94FB)]),
            borderRadius: BorderRadius.circular(20),
            boxShadow: [BoxShadow(color: Color(0xFF6C63FF).withOpacity(0.3), blurRadius: 15, offset: Offset(0, 5))],
          ),
          child: Row(
            children: [
              Container(padding: EdgeInsets.all(12), decoration: BoxDecoration(color: Colors.white24, shape: BoxShape.circle), child: Icon(Icons.emoji_events_rounded, color: Colors.white, size: 32)),
              SizedBox(width: 15),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text("تحدي اليوم", style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 18)),
                    SizedBox(height: 4),
                    Text("أجب واربح 50 نقطة XP فوراً!", style: TextStyle(color: Colors.white70, fontSize: 12)),
                  ],
                ),
              ),
              _isLoadingQuest 
                ? SizedBox(width: 20, height: 20, child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2))
                : CircleAvatar(backgroundColor: Colors.white, radius: 15, child: Icon(Icons.arrow_forward_ios_rounded, color: Color(0xFF6C63FF), size: 16)),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildFilterChip(String label) {
    bool isSelected = _selectedFilter == label;
    return Padding(
      padding: const EdgeInsets.only(left: 10.0),
      child: GestureDetector(
        onTap: () => setState(() => _selectedFilter = label),
        child: AnimatedContainer(
          duration: Duration(milliseconds: 200),
          padding: EdgeInsets.symmetric(horizontal: 16, vertical: 8),
          decoration: BoxDecoration(
            color: isSelected ? Color(0xFF6C63FF) : Theme.of(context).cardColor,
            borderRadius: BorderRadius.circular(20),
            border: Border.all(color: isSelected ? Colors.transparent : Colors.grey.withOpacity(0.2)),
            boxShadow: isSelected ? [BoxShadow(color: Color(0xFF6C63FF).withOpacity(0.3), blurRadius: 8, offset: Offset(0, 2))] : [],
          ),
          child: Text(label, style: TextStyle(color: isSelected ? Colors.white : Colors.grey[700], fontWeight: FontWeight.bold, fontSize: 13)),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// 📺 Course Details Screen (🔥 تم تجديد التصميم كلياً 🔥)
// ---------------------------------------------------------------------------
class CourseDetailsScreen extends StatefulWidget {
  final _CourseData course;
  CourseDetailsScreen({required this.course});
  @override
  _CourseDetailsScreenState createState() => _CourseDetailsScreenState();
}

class _CourseDetailsScreenState extends State<CourseDetailsScreen> {
  bool _isCompleted = false;

  @override
  void initState() {
    super.initState();
    _checkCompletion();
  }

  Future<void> _checkCompletion() async {
    final prefs = await SharedPreferences.getInstance();
    setState(() => _isCompleted = prefs.getBool('course_${widget.course.id}_completed') ?? false);
  }

  Future<void> _markCompleted() async {
    if (_isCompleted) return;
    setState(() => _isCompleted = true);
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool('course_${widget.course.id}_completed', true);
    final user = FirebaseAuth.instance.currentUser;
    if (user != null) FirebaseFirestore.instance.collection('users').doc(user.uid).update({'totalPoints': FieldValue.increment(200)});
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("🌟 +200 XP! رائع"), backgroundColor: Color(0xFF6C63FF)));
  }

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final bgColor = Theme.of(context).scaffoldBackgroundColor;
    final cardColor = Theme.of(context).cardColor;

    return Scaffold(
      backgroundColor: bgColor,
      body: CustomScrollView(
        slivers: [
          // 🔥 1. هيدر نظيف واحترافي بدون "شكل الفيديو"
          SliverAppBar(
            expandedHeight: 180,
            pinned: true,
            backgroundColor: widget.course.color,
            elevation: 0,
            flexibleSpace: FlexibleSpaceBar(
              background: Container(
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    colors: [widget.course.color, widget.course.color.withOpacity(0.7)],
                    begin: Alignment.topLeft, end: Alignment.bottomRight
                  )
                ),
                child: Stack(
                  children: [
                    // أيقونة خلفية خفيفة
                    Positioned(right: -40, bottom: -40, child: Icon(Icons.school_rounded, size: 200, color: Colors.white.withOpacity(0.1))),
                    Positioned(
                      bottom: 20, left: 20, right: 20,
                      child: Text(
                        widget.course.title,
                        style: TextStyle(color: Colors.white, fontSize: 24, fontWeight: FontWeight.bold, shadows: [Shadow(color: Colors.black26, blurRadius: 10)]),
                      ),
                    )
                  ],
                ),
              ),
            ),
          ),

          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.all(20.0),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // 🔥 2. بطاقة المدرب والتقييم
                  Container(
                    padding: EdgeInsets.all(15),
                    decoration: BoxDecoration(color: cardColor, borderRadius: BorderRadius.circular(15), boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.03), blurRadius: 10)]),
                    child: Row(
                      children: [
                        CircleAvatar(backgroundColor: widget.course.color.withOpacity(0.1), child: Icon(Icons.person, color: widget.course.color)),
                        SizedBox(width: 15),
                        Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text("المدرب", style: TextStyle(color: Colors.grey, fontSize: 12)), Text(widget.course.instructor, style: TextStyle(fontWeight: FontWeight.bold, fontSize: 15))]),
                        Spacer(),
                        Container(
                          padding: EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                          decoration: BoxDecoration(color: Colors.amber.withOpacity(0.1), borderRadius: BorderRadius.circular(20)),
                          child: Row(children: [Icon(Icons.star, color: Colors.amber, size: 16), SizedBox(width: 4), Text("${widget.course.rating}", style: TextStyle(fontWeight: FontWeight.bold, color: Colors.amber[800]))]),
                        )
                      ],
                    ),
                  ),
                  SizedBox(height: 25),

                  // 🔥 3. الوصف المطول (Tafaseel)
                  Text("عن الكورس", style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
                  SizedBox(height: 10),
                  Text(
                    widget.course.details, // استخدام التفاصيل المطولة
                    style: TextStyle(fontSize: 15, height: 1.7, color: isDark ? Colors.white70 : Colors.grey[700]),
                  ),
                  SizedBox(height: 30),

                  // 🔥 4. زر الذهاب لليوتيوب
                  SizedBox(
                    width: double.infinity,
                    height: 55,
                    child: ElevatedButton.icon(
                      onPressed: () => launchUrl(Uri.parse(widget.course.url), mode: LaunchMode.externalApplication),
                      icon: Icon(Icons.play_circle_fill_rounded),
                      label: Text("ابدأ المشاهدة الآن"),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: Color(0xFF6C63FF),
                        foregroundColor: Colors.white,
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(15)),
                        elevation: 5,
                        textStyle: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)
                      ),
                    ),
                  ),
                  SizedBox(height: 20),

                  // 🔥 5. بطاقة الإتمام
                  GestureDetector(
                    onTap: _markCompleted,
                    child: AnimatedContainer(
                      duration: Duration(milliseconds: 300),
                      padding: EdgeInsets.all(15),
                      decoration: BoxDecoration(
                        border: Border.all(color: _isCompleted ? Colors.green : Colors.grey[300]!, width: 2), 
                        borderRadius: BorderRadius.circular(15), 
                        color: _isCompleted ? Colors.green.withOpacity(0.05) : Colors.transparent
                      ),
                      child: Row(
                        children: [
                          Icon(_isCompleted ? Icons.check_circle : Icons.radio_button_unchecked, color: _isCompleted ? Colors.green : Colors.grey, size: 30),
                          SizedBox(width: 15),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(_isCompleted ? "تم الإنجاز!" : "أتممت هذا الكورس؟", style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
                                Text(_isCompleted ? "حصلت على 200 نقطة" : "اضغط هنا لاستلام 200 نقطة", style: TextStyle(color: Colors.grey[600], fontSize: 12)),
                              ],
                            ),
                          )
                        ],
                      ),
                    ),
                  ),

                  if (_isCompleted)
                    Padding(
                      padding: const EdgeInsets.only(top: 15.0),
                      child: OutlinedButton.icon(
                        onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => CertificateScreen(courseName: widget.course.title))),
                        icon: Icon(Icons.workspace_premium),
                        label: Text("استخراج الشهادة"),
                        style: OutlinedButton.styleFrom(
                          minimumSize: Size(double.infinity, 50), 
                          foregroundColor: Colors.green, 
                          side: BorderSide(color: Colors.green),
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(15))
                        ),
                      ),
                    ),
                  SizedBox(height: 50),
                ],
              ),
            ),
          )
        ],
      ),
    );
  }
}

// --- 🧩 Quest Dialog ---
class _QuestDialogUI extends StatefulWidget {
  final String question;
  final List<String> options;
  final int correctIndex;
  final String explanation;
  final VoidCallback onSuccess; 
  const _QuestDialogUI({required this.question, required this.options, required this.correctIndex, required this.explanation, required this.onSuccess});
  @override
  __QuestDialogUIState createState() => __QuestDialogUIState();
}

class __QuestDialogUIState extends State<_QuestDialogUI> {
  bool _answered = false;
  bool _isCorrect = false;
  int? _selectedIndex;

  void _checkAnswer(int idx) async {
    if (_answered) return;
    setState(() { _answered = true; _selectedIndex = idx; _isCorrect = (idx == widget.correctIndex); });
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('last_daily_quest_date', DateFormat('yyyy-MM-dd').format(DateTime.now()));
    if (_isCorrect) widget.onSuccess();
  }
  
  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      contentPadding: EdgeInsets.zero,
      scrollable: true,
      content: Container(
        padding: EdgeInsets.all(20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(_answered ? (_isCorrect ? "🎉 إجابة صحيحة!" : "😅 حظاً أوفر") : "سؤال التحدي", style: TextStyle(fontWeight: FontWeight.bold, fontSize: 18)),
            SizedBox(height: 20),
            Text(widget.question, textAlign: TextAlign.center, style: TextStyle(fontSize: 16)),
            SizedBox(height: 20),
            ...List.generate(widget.options.length, (i) {
              Color color = Colors.grey[100]!;
              if (_answered) {
                if (i == widget.correctIndex) color = Colors.green[100]!;
                else if (i == _selectedIndex) color = Colors.red[100]!;
              }
              return Container(
                margin: EdgeInsets.only(bottom: 10),
                child: InkWell(
                  onTap: () => _checkAnswer(i),
                  borderRadius: BorderRadius.circular(12),
                  child: Container(
                    padding: EdgeInsets.symmetric(vertical: 15, horizontal: 15),
                    decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(12)),
                    child: Row(children: [Expanded(child: Text(widget.options[i])), if (_answered && i == widget.correctIndex) Icon(Icons.check, color: Colors.green)]),
                  ),
                ),
              );
            }),
            if (_answered) ...[
              SizedBox(height: 20),
              Text("💡 ${widget.explanation}", style: TextStyle(fontSize: 13, color: Colors.grey[700]), textAlign: TextAlign.center),
              SizedBox(height: 20),
              ElevatedButton(onPressed: () => Navigator.pop(context), child: Text("إغلاق"), style: ElevatedButton.styleFrom(shape: StadiumBorder(), minimumSize: Size(100, 40)))
            ]
          ],
        ),
      ),
    );
  }
}