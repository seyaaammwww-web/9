import 'package:flutter/material.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:animate_do/animate_do.dart';

class StudentQuizzesScreen extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text("الاختبارات والتكليفات"),
        centerTitle: true,
        backgroundColor: Colors.transparent,
        elevation: 0,
        foregroundColor: Colors.black,
      ),
      body: StreamBuilder<QuerySnapshot>(
        stream: FirebaseFirestore.instance.collection('quizzes').orderBy('createdAt', descending: true).snapshots(),
        builder: (context, snapshot) {
          if (!snapshot.hasData) return Center(child: CircularProgressIndicator());
          
          if (snapshot.data!.docs.isEmpty) {
            return Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(Icons.assignment_turned_in_outlined, size: 80, color: Colors.grey[300]),
                  SizedBox(height: 15),
                  Text("لا توجد اختبارات متاحة حالياً", style: TextStyle(color: Colors.grey[600], fontSize: 16)),
                  Text("استرح قليلاً!", style: TextStyle(color: Colors.grey[400], fontSize: 12)),
                ],
              ),
            );
          }

          return ListView.builder(
            padding: EdgeInsets.all(20),
            itemCount: snapshot.data!.docs.length,
            itemBuilder: (ctx, i) {
              var doc = snapshot.data!.docs[i];
              var data = doc.data() as Map<String, dynamic>;
              List questions = data['questions'] ?? [];

              return FadeInUp(
                duration: Duration(milliseconds: 500),
                delay: Duration(milliseconds: i * 100),
                child: GestureDetector(
                  onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => QuizTakingScreen(quizId: doc.id, quizData: data))),
                  child: Container(
                    margin: EdgeInsets.only(bottom: 15),
                    padding: EdgeInsets.all(20),
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(20),
                      boxShadow: [BoxShadow(color: Colors.indigo.withOpacity(0.08), blurRadius: 15, offset: Offset(0, 5))],
                      border: Border.all(color: Colors.indigo.withOpacity(0.05)),
                    ),
                    child: Row(
                      children: [
                        Container(
                          padding: EdgeInsets.all(15),
                          decoration: BoxDecoration(
                            gradient: LinearGradient(colors: [Colors.indigo, Colors.blueAccent]),
                            shape: BoxShape.circle,
                            boxShadow: [BoxShadow(color: Colors.blue.withOpacity(0.3), blurRadius: 8, offset: Offset(0, 4))]
                          ),
                          child: Icon(Icons.quiz_rounded, color: Colors.white, size: 28),
                        ),
                        SizedBox(width: 15),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(data['title'] ?? "اختبار", style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
                              SizedBox(height: 6),
                              Row(
                                children: [
                                  Icon(Icons.list_alt_rounded, size: 14, color: Colors.grey),
                                  SizedBox(width: 4),
                                  Text("${questions.length} أسئلة", style: TextStyle(color: Colors.grey, fontSize: 12)),
                                  SizedBox(width: 15),
                                  Icon(Icons.category_outlined, size: 14, color: Colors.grey),
                                  SizedBox(width: 4),
                                  Text(data['subject'] ?? "عام", style: TextStyle(color: Colors.grey, fontSize: 12)),
                                ],
                              )
                            ],
                          ),
                        ),
                        Icon(Icons.arrow_forward_ios_rounded, size: 18, color: Colors.grey[300])
                      ],
                    ),
                  ),
                ),
              );
            },
          );
        },
      ),
    );
  }
}

// --- شاشة حل الاختبار ---
class QuizTakingScreen extends StatefulWidget {
  final String quizId;
  final Map<String, dynamic> quizData;
  QuizTakingScreen({required this.quizId, required this.quizData});

  @override
  _QuizTakingScreenState createState() => _QuizTakingScreenState();
}

class _QuizTakingScreenState extends State<QuizTakingScreen> {
  int _currentIndex = 0;
  int _score = 0;
  bool _isFinished = false;
  bool _isReviewing = false; // وضع المراجعة
  List<dynamic> _questions = [];
  Map<int, int> _userAnswers = {}; // تخزين إجابات الطالب: {رقم السؤال: رقم الاختيار}
  final Stopwatch _stopwatch = Stopwatch(); // لحساب الوقت

  @override
  void initState() {
    super.initState();
    _questions = widget.quizData['questions'] ?? [];
    _stopwatch.start(); // بدء الوقت
  }

  @override
  void dispose() {
    _stopwatch.stop();
    super.dispose();
  }

  void _submitAnswer(int selectedIndex) {
    // تخزين الإجابة
    _userAnswers[_currentIndex] = selectedIndex;

    if (_questions[_currentIndex]['correctIndex'] == selectedIndex) {
      _score++;
    }

    if (_currentIndex < _questions.length - 1) {
      setState(() => _currentIndex++);
    } else {
      _finishQuiz();
    }
  }

  void _finishQuiz() async {
    _stopwatch.stop();
    setState(() => _isFinished = true);
    
    // 10 نقاط لكل إجابة صحيحة
    int finalPoints = (_score * 10); 
    
    final user = FirebaseAuth.instance.currentUser;
    if (user != null) {
      // تحديث نقاط الطالب
      await FirebaseFirestore.instance.collection('users').doc(user.uid).update({
        'totalPoints': FieldValue.increment(finalPoints)
      });
      
      // تسجيل النتيجة
      FirebaseFirestore.instance.collection('quiz_results').add({
        'studentId': user.uid,
        'quizId': widget.quizId,
        'quizTitle': widget.quizData['title'],
        'score': _score,
        'total': _questions.length,
        'timeTakenSeconds': _stopwatch.elapsed.inSeconds,
        'timestamp': FieldValue.serverTimestamp(),
      });
    }
  }

  // إعادة الاختبار
  void _retryQuiz() {
    setState(() {
      _currentIndex = 0;
      _score = 0;
      _isFinished = false;
      _isReviewing = false;
      _userAnswers.clear();
      _stopwatch.reset();
      _stopwatch.start();
    });
  }

  // نافذة تأكيد الخروج
  Future<bool> _onWillPop() async {
    if (_isFinished) return true;
    return (await showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('هل أنت متأكد؟'),
        content: Text('سيتم فقدان تقدمك في هذا الاختبار إذا خرجت الآن.'),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: Text('إلغاء'),
          ),
          TextButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: Text('خروج', style: TextStyle(color: Colors.red)),
          ),
        ],
      ),
    )) ?? false;
  }

  @override
  Widget build(BuildContext context) {
    if (_questions.isEmpty) return Scaffold(appBar: AppBar(), body: Center(child: Text("عذراً، حدث خطأ في تحميل الأسئلة")));

    // 1. شاشة المراجعة (Review Mode)
    if (_isReviewing) {
      return Scaffold(
        appBar: AppBar(title: Text("مراجعة الإجابات"), centerTitle: true),
        body: ListView.builder(
          padding: EdgeInsets.all(20),
          itemCount: _questions.length,
          itemBuilder: (ctx, i) {
            final q = _questions[i];
            final userAnswer = _userAnswers[i];
            final correctAnswer = q['correctIndex'];
            final isCorrect = userAnswer == correctAnswer;

            return Card(
              margin: EdgeInsets.only(bottom: 15),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(15),
                side: BorderSide(color: isCorrect ? Colors.green : Colors.red, width: 1.5)
              ),
              child: Padding(
                padding: const EdgeInsets.all(15.0),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text("س${i+1}: ${q['question']}", style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
                    SizedBox(height: 10),
                    ...List.generate(q['options'].length, (optIndex) {
                      Color color = Colors.black87;
                      FontWeight weight = FontWeight.normal;
                      IconData? icon;

                      if (optIndex == correctAnswer) {
                        color = Colors.green[700]!;
                        weight = FontWeight.bold;
                        icon = Icons.check_circle;
                      } else if (optIndex == userAnswer && !isCorrect) {
                        color = Colors.red[700]!;
                        icon = Icons.cancel;
                      }

                      return Padding(
                        padding: const EdgeInsets.symmetric(vertical: 4.0),
                        child: Row(
                          children: [
                            if (icon != null) Icon(icon, size: 16, color: color),
                            if (icon != null) SizedBox(width: 8),
                            Expanded(child: Text(q['options'][optIndex], style: TextStyle(color: color, fontWeight: weight))),
                          ],
                        ),
                      );
                    }),
                  ],
                ),
              ),
            );
          },
        ),
        bottomNavigationBar: Padding(
          padding: const EdgeInsets.all(20.0),
          child: ElevatedButton(
            onPressed: () => setState(() => _isReviewing = false),
            child: Text("العودة للنتيجة"),
            style: ElevatedButton.styleFrom(backgroundColor: Color(0xFF6C63FF), foregroundColor: Colors.white),
          ),
        ),
      );
    }

    // 2. شاشة النتيجة النهائية
    if (_isFinished) {
      final minutes = _stopwatch.elapsed.inMinutes;
      final seconds = _stopwatch.elapsed.inSeconds % 60;
      
      return Scaffold(
        backgroundColor: Colors.white,
        body: Center(
          child: FadeInUp(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(30.0),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Container(
                    padding: EdgeInsets.all(30),
                    decoration: BoxDecoration(color: _score > (_questions.length/2) ? Colors.green[50] : Colors.orange[50], shape: BoxShape.circle),
                    child: Icon(
                      _score > (_questions.length/2) ? Icons.emoji_events_rounded : Icons.sentiment_satisfied_alt, 
                      size: 80, 
                      color: _score > (_questions.length/2) ? Colors.green : Colors.orange
                    ),
                  ),
                  SizedBox(height: 30),
                  
                  Text("انتهى الاختبار!", style: TextStyle(fontSize: 28, fontWeight: FontWeight.bold, color: Colors.black87)),
                  SizedBox(height: 10),
                  Text("الوقت المستغرق: $minutes دقيقة و $seconds ثانية", style: TextStyle(color: Colors.grey[600], fontSize: 14)),
                  
                  SizedBox(height: 30),
                  
                  // كروت الإحصائيات
                  Row(
                    children: [
                      Expanded(
                        child: _buildStatCard("النتيجة", "$_score/${_questions.length}", Colors.blue),
                      ),
                      SizedBox(width: 15),
                      Expanded(
                        child: _buildStatCard("XP مكتسبة", "+${_score * 10}", Colors.amber),
                      ),
                    ],
                  ),

                  SizedBox(height: 50),
                  
                  // أزرار التحكم
                  SizedBox(
                    width: double.infinity,
                    height: 50,
                    child: OutlinedButton.icon(
                      onPressed: () => setState(() => _isReviewing = true),
                      icon: Icon(Icons.playlist_add_check),
                      label: Text("مراجعة الإجابات"),
                      style: OutlinedButton.styleFrom(foregroundColor: Colors.black87, shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(15))),
                    ),
                  ),
                  SizedBox(height: 15),
                  Row(
                    children: [
                      Expanded(
                        child: ElevatedButton.icon(
                          onPressed: _retryQuiz,
                          icon: Icon(Icons.refresh),
                          label: Text("إعادة"),
                          style: ElevatedButton.styleFrom(backgroundColor: Colors.orange, foregroundColor: Colors.white, shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(15))),
                        ),
                      ),
                      SizedBox(width: 15),
                      Expanded(
                        child: ElevatedButton.icon(
                          onPressed: () => Navigator.pop(context),
                          icon: Icon(Icons.home),
                          label: Text("الرئيسية"),
                          style: ElevatedButton.styleFrom(backgroundColor: Color(0xFF6C63FF), foregroundColor: Colors.white, shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(15))),
                        ),
                      ),
                    ],
                  )
                ],
              ),
            ),
          ),
        ),
      );
    }

    // 3. شاشة الاختبار (الوضع العادي)
    var currentQ = _questions[_currentIndex];
    
    return WillPopScope( // حماية الخروج
      onWillPop: _onWillPop,
      child: Scaffold(
        backgroundColor: Color(0xFFF3F6F8),
        appBar: AppBar(
          title: Text("سؤال ${_currentIndex + 1} من ${_questions.length}"),
          centerTitle: true,
          backgroundColor: Colors.transparent,
          elevation: 0,
          foregroundColor: Colors.black,
          automaticallyImplyLeading: false,
          actions: [
            IconButton(icon: Icon(Icons.close), onPressed: () => _onWillPop().then((val) => val ? Navigator.pop(context) : null))
          ],
        ),
        body: Padding(
          padding: const EdgeInsets.all(20.0),
          child: Column(
            children: [
              ClipRRect(
                borderRadius: BorderRadius.circular(10),
                child: LinearProgressIndicator(
                  value: (_currentIndex + 1) / _questions.length,
                  backgroundColor: Colors.grey[300],
                  color: Color(0xFF6C63FF),
                  minHeight: 8,
                ),
              ),
              SizedBox(height: 40),
              
              FadeInDown(
                key: ValueKey(_currentIndex),
                child: Container(
                  width: double.infinity,
                  padding: EdgeInsets.all(25),
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(20),
                    boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 15, offset: Offset(0, 5))],
                  ),
                  child: Text(
                    currentQ['question'],
                    style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, height: 1.5),
                    textAlign: TextAlign.center,
                  ),
                ),
              ),
              
              SizedBox(height: 30),
              
              Expanded(
                child: ListView.builder(
                  itemCount: currentQ['options'].length,
                  itemBuilder: (ctx, index) {
                    return FadeInUp(
                      delay: Duration(milliseconds: index * 100),
                      child: Container(
                        margin: EdgeInsets.only(bottom: 15),
                        width: double.infinity,
                        child: ElevatedButton(
                          onPressed: () => _submitAnswer(index),
                          style: ElevatedButton.styleFrom(
                            backgroundColor: Colors.white,
                            foregroundColor: Colors.black87,
                            padding: EdgeInsets.symmetric(vertical: 20, horizontal: 20),
                            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(15)),
                            elevation: 2,
                            alignment: Alignment.centerRight
                          ),
                          child: Row(
                            children: [
                              CircleAvatar(
                                radius: 12,
                                backgroundColor: Colors.grey[100],
                                child: Text(["A", "B", "C", "D"][index], style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: Colors.black54)),
                              ),
                              SizedBox(width: 15),
                              Expanded(child: Text(currentQ['options'][index], style: TextStyle(fontSize: 16))),
                            ],
                          ),
                        ),
                      ),
                    );
                  },
                ),
              )
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildStatCard(String title, String value, Color color) {
    return Container(
      padding: EdgeInsets.symmetric(vertical: 20),
      decoration: BoxDecoration(
        color: color.withOpacity(0.1),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color.withOpacity(0.3))
      ),
      child: Column(
        children: [
          Text(title, style: TextStyle(color: color.withOpacity(0.8), fontWeight: FontWeight.bold)),
          SizedBox(height: 5),
          Text(value, style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold, color: color)),
        ],
      ),
    );
  }
}