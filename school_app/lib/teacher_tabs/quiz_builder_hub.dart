import 'package:flutter/material.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:animate_do/animate_do.dart';

class QuizBuilderHub extends StatefulWidget {
  @override
  _QuizBuilderHubState createState() => _QuizBuilderHubState();
}

class _QuizBuilderHubState extends State<QuizBuilderHub> {
  String _searchQuery = "";
  final TextEditingController _searchController = TextEditingController();

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final bgColor = Theme.of(context).scaffoldBackgroundColor;
    final cardColor = Theme.of(context).cardColor;
    final primaryColor = Color(0xFF6C63FF);

    return Scaffold(
      backgroundColor: bgColor,
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => Navigator.push(
            context, MaterialPageRoute(builder: (_) => QuizEditorScreen())),
        backgroundColor: primaryColor,
        elevation: 4,
        icon: Icon(Icons.add, color: Colors.white),
        label: Text("اختبار جديد",
            style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
      ),
      body: CustomScrollView(
        physics: BouncingScrollPhysics(),
        slivers: [
          // 1. الهيدر وشريط البحث (تم الإصلاح هنا)
          SliverAppBar(
            expandedHeight: 200, // تمت الزيادة من 160 إلى 200
            pinned: true,
            backgroundColor: isDark ? Color(0xFF1E1E2C) : Colors.white,
            elevation: 0,
            flexibleSpace: FlexibleSpaceBar(
              background: Padding(
                // تم تعديل الحواشي لتناسب الارتفاع الجديد
                padding: const EdgeInsets.fromLTRB(20, 70, 20, 60),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text("بنك الاختبارات",
                        style: TextStyle(
                            fontSize: 28,
                            fontWeight: FontWeight.bold,
                            color: primaryColor)),
                    SizedBox(height: 5),
                    Text("قم بإنشاء وإدارة اختبارات طلابك بسهولة",
                        style: TextStyle(color: Colors.grey)),
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
                      boxShadow: [
                        BoxShadow(
                            color: Colors.black.withOpacity(0.05),
                            blurRadius: 10,
                            offset: Offset(0, 5))
                      ]),
                  child: TextField(
                    controller: _searchController,
                    onChanged: (val) => setState(() => _searchQuery = val),
                    decoration: InputDecoration(
                      hintText: "بحث عن اختبار...",
                      prefixIcon: Icon(Icons.search, color: primaryColor),
                      border: InputBorder.none,
                      contentPadding:
                          EdgeInsets.symmetric(horizontal: 20, vertical: 15),
                    ),
                  ),
                ),
              ),
            ),
          ),

          // 2. قائمة الاختبارات
          SliverToBoxAdapter(
            child: StreamBuilder<QuerySnapshot>(
              stream: FirebaseFirestore.instance
                  .collection('quizzes')
                  .orderBy('createdAt', descending: true)
                  .snapshots(),
              builder: (context, snapshot) {
                if (!snapshot.hasData)
                  return Center(
                      child: CircularProgressIndicator(color: primaryColor));

                var docs = snapshot.data!.docs.where((doc) {
                  var data = doc.data() as Map<String, dynamic>;
                  return data['title']
                      .toString()
                      .toLowerCase()
                      .contains(_searchQuery.toLowerCase());
                }).toList();

                if (docs.isEmpty) {
                  return Center(
                      child: Padding(
                    padding: const EdgeInsets.only(top: 50),
                    child: Column(
                      children: [
                        Icon(Icons.assignment_outlined,
                            size: 80, color: Colors.grey[300]),
                        Text("لا توجد اختبارات",
                            style: TextStyle(color: Colors.grey)),
                      ],
                    ),
                  ));
                }

                return ListView.builder(
                  padding: EdgeInsets.fromLTRB(20, 10, 20, 100),
                  shrinkWrap: true,
                  physics: NeverScrollableScrollPhysics(),
                  itemCount: docs.length,
                  itemBuilder: (ctx, i) =>
                      _buildQuizCard(context, docs[i], cardColor, isDark),
                );
              },
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildQuizCard(
      BuildContext context, DocumentSnapshot doc, Color cardColor, bool isDark) {
    var data = doc.data() as Map<String, dynamic>;
    bool isActive = data['isActive'] ?? true;
    int qCount = (data['questions'] as List).length;

    return FadeInUp(
      duration: Duration(milliseconds: 400),
      child: Container(
        margin: EdgeInsets.only(bottom: 15),
        decoration: BoxDecoration(
          color: cardColor,
          borderRadius: BorderRadius.circular(20),
          boxShadow: [
            BoxShadow(
                color: Colors.black.withOpacity(0.05),
                blurRadius: 10,
                offset: Offset(0, 4))
          ],
          border: Border.all(
              color: isActive ? Colors.transparent : Colors.grey.withOpacity(0.3)),
        ),
        child: ListTile(
          contentPadding: EdgeInsets.symmetric(horizontal: 20, vertical: 15),
          leading: Container(
            padding: EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: isActive
                  ? Colors.orange.withOpacity(0.1)
                  : Colors.grey.withOpacity(0.1),
              shape: BoxShape.circle,
            ),
            child: Icon(Icons.quiz_rounded,
                color: isActive ? Colors.orange : Colors.grey, size: 28),
          ),
          title: Text(data['title'],
              style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
          subtitle: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SizedBox(height: 6),
              Text(data['subject'] ?? "عام",
                  style: TextStyle(color: Colors.grey, fontSize: 12)),
              SizedBox(height: 4),
              Row(
                children: [
                  Icon(Icons.timer_outlined, size: 14, color: Colors.blue),
                  SizedBox(width: 4),
                  Text("${data['duration'] ?? 30} دقيقة",
                      style: TextStyle(fontSize: 11, color: Colors.blue)),
                  SizedBox(width: 10),
                  Icon(Icons.list_alt, size: 14, color: Colors.purple),
                  SizedBox(width: 4),
                  Text("$qCount أسئلة",
                      style: TextStyle(fontSize: 11, color: Colors.purple)),
                ],
              )
            ],
          ),
          trailing: PopupMenuButton<String>(
            icon: Icon(Icons.more_vert, color: Colors.grey),
            onSelected: (val) async {
              if (val == 'edit') {
                Navigator.push(
                    context,
                    MaterialPageRoute(
                        builder: (_) =>
                            QuizEditorScreen(quizId: doc.id, quizData: data)));
              } else if (val == 'delete') {
                doc.reference.delete();
              } else if (val == 'toggle') {
                await doc.reference.update({'isActive': !isActive});
              }
            },
            itemBuilder: (ctx) => [
              PopupMenuItem(
                  value: 'edit',
                  child: Row(children: [
                    Icon(Icons.edit, size: 18),
                    SizedBox(width: 10),
                    Text("تعديل")
                  ])),
              PopupMenuItem(
                  value: 'toggle',
                  child: Row(children: [
                    Icon(isActive ? Icons.visibility_off : Icons.visibility,
                        size: 18),
                    SizedBox(width: 10),
                    Text(isActive ? "إخفاء" : "نشر")
                  ])),
              PopupMenuItem(
                  value: 'delete',
                  child: Row(children: [
                    Icon(Icons.delete, color: Colors.red, size: 18),
                    SizedBox(width: 10),
                    Text("حذف", style: TextStyle(color: Colors.red))
                  ])),
            ],
          ),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// 📝 شاشة محرر الاختبار (بتصميم Content Manager النظيف)
// ---------------------------------------------------------------------------
class QuizEditorScreen extends StatefulWidget {
  final String? quizId;
  final Map<String, dynamic>? quizData;

  QuizEditorScreen({this.quizId, this.quizData});

  @override
  _QuizEditorScreenState createState() => _QuizEditorScreenState();
}

class _QuizEditorScreenState extends State<QuizEditorScreen> {
  final _formKey = GlobalKey<FormState>();

  final TextEditingController _titleCtrl = TextEditingController();
  final TextEditingController _subjectCtrl = TextEditingController();
  final TextEditingController _durationCtrl = TextEditingController();

  List<Map<String, dynamic>> _questions = [];
  bool _isLoading = false;

  @override
  void initState() {
    super.initState();
    if (widget.quizData != null) {
      _titleCtrl.text = widget.quizData!['title'];
      _subjectCtrl.text = widget.quizData!['subject'];
      _durationCtrl.text = (widget.quizData!['duration'] ?? 30).toString();
      _questions =
          List<Map<String, dynamic>>.from(widget.quizData!['questions']);
    } else {
      _addQuestion();
    }
  }

  void _addQuestion() {
    setState(() {
      _questions.add({
        'question': '',
        'options': ['', '', '', ''],
        'correctIndex': 0
      });
    });
  }

  void _saveQuiz() async {
    if (!_formKey.currentState!.validate()) return;
    if (_questions.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text("يجب إضافة سؤال واحد على الأقل")));
      return;
    }

    setState(() => _isLoading = true);

    Map<String, dynamic> data = {
      'title': _titleCtrl.text,
      'subject': _subjectCtrl.text,
      'duration': int.tryParse(_durationCtrl.text) ?? 30,
      'questions': _questions,
      'createdAt': FieldValue.serverTimestamp(),
      'isActive': true,
      'teacherId': FirebaseAuth.instance.currentUser?.uid,
    };

    try {
      if (widget.quizId != null) {
        await FirebaseFirestore.instance
            .collection('quizzes')
            .doc(widget.quizId)
            .update(data);
      } else {
        data['takersCount'] = 0;
        await FirebaseFirestore.instance.collection('quizzes').add(data);
      }
      Navigator.pop(context);
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text("تم الحفظ بنجاح ✅"), backgroundColor: Colors.green));
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text("حدث خطأ ما"), backgroundColor: Colors.red));
    } finally {
      setState(() => _isLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final cardColor = Theme.of(context).cardColor;

    return Scaffold(
      backgroundColor: Theme.of(context).scaffoldBackgroundColor,
      appBar: AppBar(
        title: Text(
            widget.quizId == null ? "إنشاء اختبار جديد" : "تعديل الاختبار"),
        centerTitle: true,
        elevation: 0,
        backgroundColor: isDark ? Color(0xFF1E1E2C) : Colors.white,
        foregroundColor: isDark ? Colors.white : Colors.black,
        actions: [
          IconButton(
              icon: Icon(Icons.check, color: Color(0xFF6C63FF)),
              onPressed: _saveQuiz),
        ],
      ),
      body: Form(
        key: _formKey,
        child: SingleChildScrollView(
          padding: EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // 1. كارت البيانات الأساسية (بتصميم نظيف)
              Container(
                padding: EdgeInsets.all(20),
                decoration: BoxDecoration(
                  color: cardColor,
                  borderRadius: BorderRadius.circular(20),
                  boxShadow: [
                    BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 10)
                  ],
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text("📝 البيانات الأساسية",
                        style: TextStyle(
                            fontSize: 18,
                            fontWeight: FontWeight.bold,
                            color: Color(0xFF6C63FF))),
                    SizedBox(height: 20),
                    _buildInput(_titleCtrl, "عنوان الاختبار", isDark),
                    SizedBox(height: 15),
                    Row(
                      children: [
                        Expanded(
                            child: _buildInput(_subjectCtrl, "المادة", isDark)),
                        SizedBox(width: 15),
                        Expanded(
                            child: _buildInput(
                                _durationCtrl, "المدة (دقيقة)", isDark,
                                isNumber: true)),
                      ],
                    ),
                  ],
                ),
              ),

              SizedBox(height: 25),
              Text("❓ الأسئلة",
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
              SizedBox(height: 10),

              // 2. قائمة الأسئلة
              ListView.builder(
                shrinkWrap: true,
                physics: NeverScrollableScrollPhysics(),
                itemCount: _questions.length,
                itemBuilder: (ctx, index) {
                  return _buildQuestionCard(index, isDark, cardColor);
                },
              ),

              SizedBox(height: 20),

              // زر إضافة سؤال
              SizedBox(
                width: double.infinity,
                height: 50,
                child: OutlinedButton.icon(
                  onPressed: _addQuestion,
                  icon: Icon(Icons.add_circle_outline),
                  label: Text("إضافة سؤال جديد"),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: Color(0xFF6C63FF),
                    side: BorderSide(color: Color(0xFF6C63FF)),
                    shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(15)),
                  ),
                ),
              ),
              SizedBox(height: 50),
            ],
          ),
        ),
      ),
    );
  }

  // حقل الإدخال النظيف (نفس تصميم Content Manager)
  Widget _buildInput(
      TextEditingController controller, String label, bool isDark,
      {bool isNumber = false}) {
    return TextFormField(
      controller: controller,
      keyboardType: isNumber ? TextInputType.number : TextInputType.text,
      style: TextStyle(color: isDark ? Colors.white : Colors.black87),
      validator: (v) => v!.isEmpty ? "مطلوب" : null,
      decoration: InputDecoration(
        labelText: label,
        labelStyle: TextStyle(color: Colors.grey),
        filled: true,
        fillColor: isDark ? Colors.grey[800] : Colors.grey[100],
        border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(15), borderSide: BorderSide.none),
        contentPadding: EdgeInsets.symmetric(horizontal: 20, vertical: 16),
      ),
    );
  }

  // كارت السؤال (تصميم محسن)
  Widget _buildQuestionCard(int index, bool isDark, Color cardColor) {
    return FadeInUp(
      duration: Duration(milliseconds: 300),
      child: Container(
        margin: EdgeInsets.only(bottom: 15),
        decoration: BoxDecoration(
          color: cardColor,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: Colors.grey.withOpacity(0.1)),
          boxShadow: [
            BoxShadow(color: Colors.black.withOpacity(0.03), blurRadius: 5)
          ],
        ),
        child: Theme(
          data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
          child: ExpansionTile(
            key: ValueKey(index),
            title: Text(
              _questions[index]['question'].isEmpty
                  ? "سؤال جديد ${index + 1}"
                  : _questions[index]['question'],
              style: TextStyle(fontWeight: FontWeight.bold, fontSize: 15),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
            leading: Container(
              padding: EdgeInsets.all(8),
              decoration: BoxDecoration(
                  color: Color(0xFF6C63FF).withOpacity(0.1),
                  shape: BoxShape.circle),
              child: Text("${index + 1}",
                  style: TextStyle(
                      color: Color(0xFF6C63FF), fontWeight: FontWeight.bold)),
            ),
            trailing: IconButton(
              icon: Icon(Icons.delete_outline, color: Colors.red[300]),
              onPressed: () => setState(() => _questions.removeAt(index)),
            ),
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
                child: Column(
                  children: [
                    // حقل نص السؤال
                    TextFormField(
                      initialValue: _questions[index]['question'],
                      onChanged: (v) => _questions[index]['question'] = v,
                      style: TextStyle(
                          color: isDark ? Colors.white : Colors.black87),
                      decoration: InputDecoration(
                        hintText: "اكتب السؤال هنا...",
                        filled: true,
                        fillColor: isDark ? Colors.black26 : Colors.white,
                        border: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(12),
                            borderSide:
                                BorderSide(color: Colors.grey.withOpacity(0.3))),
                      ),
                    ),
                    SizedBox(height: 15),
                    // الخيارات
                    ...List.generate(
                        4,
                        (optIndex) => Padding(
                              padding: const EdgeInsets.only(bottom: 8.0),
                              child: Row(
                                children: [
                                  Radio<int>(
                                    value: optIndex,
                                    groupValue: _questions[index]
                                        ['correctIndex'],
                                    activeColor: Colors.green,
                                    onChanged: (val) => setState(() =>
                                        _questions[index]['correctIndex'] = val),
                                  ),
                                  Expanded(
                                    child: TextFormField(
                                      initialValue: _questions[index]['options']
                                          [optIndex],
                                      onChanged: (v) => _questions[index]
                                          ['options'][optIndex] = v,
                                      style: TextStyle(fontSize: 13),
                                      decoration: InputDecoration(
                                        hintText: "الخيار ${optIndex + 1}",
                                        isDense: true,
                                        contentPadding: EdgeInsets.symmetric(
                                            horizontal: 15, vertical: 12),
                                        filled: true,
                                        fillColor: isDark
                                            ? Colors.black26
                                            : Colors.grey[50],
                                        border: OutlineInputBorder(
                                            borderRadius:
                                                BorderRadius.circular(10),
                                            borderSide: BorderSide.none),
                                      ),
                                    ),
                                  ),
                                ],
                              ),
                            )),
                  ],
                ),
              )
            ],
          ),
        ),
      ),
    );
  }
}