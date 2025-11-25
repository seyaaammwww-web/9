import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:file_picker/file_picker.dart';
import 'package:syncfusion_flutter_pdf/pdf.dart';
import 'package:google_generative_ai/google_generative_ai.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:animate_do/animate_do.dart';

enum AnalysisType { audioUpload, pdf }

class AIAnalyzerScreen extends StatefulWidget {
  final AnalysisType type;
  const AIAnalyzerScreen({Key? key, required this.type}) : super(key: key);

  @override
  _AIAnalyzerScreenState createState() => _AIAnalyzerScreenState();
}

class _AIAnalyzerScreenState extends State<AIAnalyzerScreen> {
  // --- متغيرات الملف والتحليل ---
  String? _selectedFilePath;
  String? _fileName;
  String? _extractedText;
  
  // --- متغيرات الإعدادات ---
  String _selectedDifficulty = 'متوسط';
  String _selectedLanguage = 'العربية';
  int _questionCount = 3;
  
  // --- متغيرات الحالة ---
  bool _isLoading = false;
  String _loadingMessage = "";
  Map<String, dynamic>? _aiResult;
  
  // --- متغيرات الاختبار ---
  Map<int, int> _userAnswers = {};
  int _score = 0;
  bool _quizSubmitted = false;
  bool _isSaving = false;

  final String apiKey = 'AIzaSyAP5WCqlWMylEUAjrCG8tn7KRE1kQd4mwE'; // تأكد من مفتاحك

  // --- دوال اختيار الملف ---
  Future<void> _pickFile() async {
    try {
      FilePickerResult? result = await FilePicker.platform.pickFiles(
        type: FileType.custom, 
        allowedExtensions: widget.type == AnalysisType.pdf 
            ? ['pdf'] 
            : ['mp3', 'wav', 'm4a', 'aac'],
      );
      if (result != null) {
        setState(() { 
          _selectedFilePath = result.files.single.path;
          _fileName = result.files.single.name;
          _aiResult = null; 
          _extractedText = null;
          _loadingMessage = "جاري قراءة الملف...";
        });
        
        if (widget.type == AnalysisType.pdf && _selectedFilePath != null) {
           _extractPdfText();
        }
      }
    } catch (e) { print("Pick Error: $e"); }
  }

  Future<void> _extractPdfText() async {
    try {
      final PdfDocument document = PdfDocument(inputBytes: File(_selectedFilePath!).readAsBytesSync());
      String text = PdfTextExtractor(document).extractText();
      document.dispose();
      setState(() => _extractedText = text);
    } catch (e) {
      _showSnack("تعذر قراءة ملف PDF", Colors.red);
    }
  }

  // --- دالة التحليل الرئيسية ---
  Future<void> _analyzeContent() async {
    if (widget.type == AnalysisType.pdf && (_extractedText == null || _extractedText!.isEmpty)) return;
    if (widget.type != AnalysisType.pdf && _selectedFilePath == null) return;

    setState(() {
      _isLoading = true;
      _loadingMessage = "الذكاء الاصطناعي يحلل المحتوى...";
    });

    try {
      final model = GenerativeModel(model: 'gemini-1.5-flash', apiKey: apiKey); // استخدام موديل أسرع
      List<Part> parts = [];
      
      // برومبت محسن وذكي يقبل المتغيرات
      String sysPrompt = """
        Analyze the provided content and Generate a JSON response based on these settings:
        - Target Audience Level: $_selectedDifficulty
        - Output Language: $_selectedLanguage
        - Number of Quiz Questions: $_questionCount
        
        Requirements:
        1. A Comprehensive Summary (in $_selectedLanguage).
        2. A Quiz with exactly $_questionCount questions.
        
        Response Format (Strict JSON Only, no markdown):
        { 
          "summary": "Place summary here...", 
          "quiz": [ 
            { 
              "question": "Question text?", 
              "options": ["Option A", "Option B", "Option C", "Option D"], 
              "correct_index": 0,
              "explanation": "Why this is correct..."
            } 
          ] 
        }
      """;
      
      parts.add(TextPart(sysPrompt));

      if (widget.type == AnalysisType.pdf) {
        String text = _extractedText!;
        parts.add(TextPart(text.length > 80000 ? text.substring(0, 80000) : text));
      } else {
        setState(() => _loadingMessage = "جاري معالجة الصوت...");
        final fileBytes = await File(_selectedFilePath!).readAsBytes();
        parts.add(DataPart('audio/mp3', fileBytes));
      }

      setState(() => _loadingMessage = "جاري صياغة الأسئلة والملخص...");
      
      final response = await model.generateContent([Content.multi(parts)]);
      String jsonStr = response.text ?? "";
      
      // تنظيف الـ JSON
      jsonStr = jsonStr.replaceAll('```json', '').replaceAll('```', '').trim();
      if (jsonStr.contains('{')) {
        jsonStr = jsonStr.substring(jsonStr.indexOf('{'), jsonStr.lastIndexOf('}') + 1);
      }
      
      setState(() {
        _aiResult = jsonDecode(jsonStr);
        _userAnswers.clear();
        _quizSubmitted = false;
      });
    } catch (e) {
      _showSnack("حدث خطأ أثناء التحليل، حاول مرة أخرى.", Colors.red);
    } finally {
      setState(() => _isLoading = false);
    }
  }

  Future<void> _submitQuiz() async {
    if (_aiResult == null) return;
    int correct = 0;
    var quiz = _aiResult!['quiz'];
    for (int i = 0; i < quiz.length; i++) {
      if (_userAnswers[i] == quiz[i]['correct_index']) correct++;
    }
    
    int finalScore = ((correct / quiz.length) * 100).toInt();
    setState(() { _score = finalScore; _quizSubmitted = true; });

    // تسجيل النقاط
    final user = FirebaseAuth.instance.currentUser;
    if (user != null) {
      await FirebaseFirestore.instance.collection('users').doc(user.uid).update({
        'totalPoints': FieldValue.increment(finalScore)
      });
    }
    _showSnack("تم اعتماد نتيجتك: $finalScore%", Colors.green);
  }

  // --- ميزة الحفظ الجديدة ---
  Future<void> _saveAnalysis() async {
    if (_aiResult == null) return;
    setState(() => _isSaving = true);
    final user = FirebaseAuth.instance.currentUser;
    if (user != null) {
      try {
        await FirebaseFirestore.instance.collection('users').doc(user.uid).collection('saved_analyses').add({
          'fileName': _fileName,
          'type': widget.type == AnalysisType.pdf ? 'PDF' : 'Audio',
          'summary': _aiResult!['summary'],
          'score': _quizSubmitted ? _score : null,
          'date': FieldValue.serverTimestamp(),
          'tags': [_selectedDifficulty, _selectedLanguage]
        });
        _showSnack("تم حفظ التحليل في ملاحظاتك", Colors.green);
      } catch (e) {
        _showSnack("فشل الحفظ", Colors.red);
      }
    }
    setState(() => _isSaving = false);
  }

  void _showSnack(String msg, Color color) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg), backgroundColor: color));

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text("المحلل الذكي Pro"),
        actions: [
          if (_aiResult != null)
            IconButton(
              icon: _isSaving 
                ? SizedBox(width: 20, height: 20, child: CircularProgressIndicator(color: Colors.black, strokeWidth: 2)) 
                : Icon(Icons.bookmark_add_outlined),
              onPressed: _isSaving ? null : _saveAnalysis,
              tooltip: "حفظ في الملاحظات",
            )
        ],
      ),
      body: Padding(
        padding: const EdgeInsets.all(20),
        child: _isLoading 
          ? _buildLoadingState()
          : (_aiResult == null ? _buildInputSection() : _buildResultSection()),
      ),
    );
  }

  Widget _buildLoadingState() {
    return Center(
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        CircularProgressIndicator(color: Color(0xFF6C63FF)), 
        SizedBox(height: 25), 
        Text(_loadingMessage, style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
        SizedBox(height: 10),
        Text("قد يستغرق هذا بضع ثوانٍ...", style: TextStyle(color: Colors.grey, fontSize: 12)),
      ]),
    );
  }

  Widget _buildInputSection() {
    return Center(
      child: SingleChildScrollView(
        child: FadeInUp(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              // أيقونة اختيار الملف
              GestureDetector(
                onTap: _pickFile,
                child: Container(
                  padding: EdgeInsets.all(30),
                  decoration: BoxDecoration(
                    gradient: LinearGradient(colors: [Color(0xFF6C63FF).withOpacity(0.1), Colors.blue.withOpacity(0.1)]),
                    shape: BoxShape.circle,
                    border: Border.all(color: Color(0xFF6C63FF).withOpacity(0.3), width: 2, style: BorderStyle.solid)
                  ),
                  child: Icon(widget.type == AnalysisType.pdf ? Icons.picture_as_pdf_rounded : Icons.mic_rounded, size: 60, color: Color(0xFF6C63FF)),
                ),
              ),
              SizedBox(height: 20),
              Text(_selectedFilePath == null ? (widget.type == AnalysisType.pdf ? "اضغط لرفع PDF" : "اضغط لرفع ملف صوتي") : "تم اختيار: $_fileName", 
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: _selectedFilePath != null ? Colors.green : Colors.black87),
                textAlign: TextAlign.center,
              ),
              
              if (_selectedFilePath != null) ...[
                Divider(height: 40),
                // قسم الإعدادات
                Container(
                  padding: EdgeInsets.all(20),
                  decoration: BoxDecoration(
                    color: Colors.grey[50],
                    borderRadius: BorderRadius.circular(20),
                    border: Border.all(color: Colors.grey[200]!)
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text("⚙️ إعدادات التحليل", style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16, color: Color(0xFF6C63FF))),
                      SizedBox(height: 15),
                      
                      _buildDropdown("مستوى الشرح", _selectedDifficulty, ["مبتدئ", "متوسط", "متقدم"], (v) => setState(() => _selectedDifficulty = v!)),
                      SizedBox(height: 10),
                      _buildDropdown("اللغة", _selectedLanguage, ["العربية", "English"], (v) => setState(() => _selectedLanguage = v!)),
                      SizedBox(height: 10),
                      Text("عدد الأسئلة: $_questionCount", style: TextStyle(fontSize: 14)),
                      Slider(
                        value: _questionCount.toDouble(),
                        min: 3, max: 10, divisions: 7,
                        activeColor: Color(0xFF6C63FF),
                        label: _questionCount.toString(),
                        onChanged: (v) => setState(() => _questionCount = v.toInt()),
                      )
                    ],
                  ),
                ),
                SizedBox(height: 25),
                SizedBox(
                  width: double.infinity,
                  height: 50,
                  child: ElevatedButton(
                    onPressed: _analyzeContent, 
                    child: Text("بدء التحليل الذكي"),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Color(0xFF6C63FF), 
                      foregroundColor: Colors.white,
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(15))
                    )
                  ),
                )
              ]
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildDropdown(String label, String value, List<String> items, Function(String?) onChanged) {
    return Row(
      children: [
        Expanded(child: Text(label, style: TextStyle(fontSize: 14))),
        Container(
          padding: EdgeInsets.symmetric(horizontal: 12),
          decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(10), border: Border.all(color: Colors.grey[300]!)),
          child: DropdownButton<String>(
            value: value,
            underline: SizedBox(),
            items: items.map((e) => DropdownMenuItem(value: e, child: Text(e, style: TextStyle(fontSize: 13)))).toList(),
            onChanged: onChanged,
          ),
        )
      ],
    );
  }

  Widget _buildResultSection() {
    return SingleChildScrollView(
      child: FadeInUp(
        child: Column(
          children: [
            // بطاقة الملخص
            Container(
              width: double.infinity,
              padding: EdgeInsets.all(20),
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(20),
                boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 10, offset: Offset(0, 5))]
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(children: [Icon(Icons.auto_awesome, color: Colors.amber), SizedBox(width: 8), Text("ملخص المحتوى", style: TextStyle(fontWeight: FontWeight.bold, fontSize: 18))]),
                  Divider(height: 25),
                  Text(_aiResult!['summary'], style: TextStyle(height: 1.6, fontSize: 15, color: Colors.black87)),
                ],
              ),
            ),
            
            SizedBox(height: 25),
            
            // عنوان الاختبار
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text("اختبر فهمك", style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
                if (_quizSubmitted)
                  Container(
                    padding: EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                    decoration: BoxDecoration(color: _score >= 50 ? Colors.green[100] : Colors.red[100], borderRadius: BorderRadius.circular(20)),
                    child: Text("النتيجة: $_score%", style: TextStyle(color: _score >= 50 ? Colors.green[800] : Colors.red[800], fontWeight: FontWeight.bold)),
                  )
              ],
            ),
            SizedBox(height: 15),
            
            // قائمة الأسئلة
            ...List.generate(_aiResult!['quiz'].length, (index) {
              var q = _aiResult!['quiz'][index];
              bool isCorrect = _quizSubmitted && _userAnswers[index] == q['correct_index'];
              bool isWrong = _quizSubmitted && _userAnswers[index] != q['correct_index'] && _userAnswers[index] != null;
              
              return Card(
                margin: EdgeInsets.only(bottom: 15),
                elevation: 2,
                shape: RoundedRectangleBorder(
                  side: BorderSide(color: isCorrect ? Colors.green : (isWrong ? Colors.red : Colors.transparent), width: 1.5),
                  borderRadius: BorderRadius.circular(15)
                ),
                child: Padding(
                  padding: const EdgeInsets.all(15.0),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text("س${index+1}: ${q['question']}", style: TextStyle(fontWeight: FontWeight.bold, fontSize: 15)),
                      SizedBox(height: 10),
                      ...List.generate(q['options'].length, (optI) => RadioListTile<int>(
                        title: Text(q['options'][optI], style: TextStyle(fontSize: 14)),
                        value: optI,
                        contentPadding: EdgeInsets.zero,
                        dense: true,
                        groupValue: _userAnswers[index],
                        onChanged: _quizSubmitted ? null : (v) => setState(() => _userAnswers[index] = v!),
                        activeColor: Color(0xFF6C63FF),
                      )),
                      if (_quizSubmitted) 
                        AnimatedContainer(
                          duration: Duration(milliseconds: 300),
                          margin: EdgeInsets.only(top: 10),
                          padding: EdgeInsets.all(12),
                          width: double.infinity,
                          decoration: BoxDecoration(color: Colors.blue[50], borderRadius: BorderRadius.circular(10)),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text("💡 شرح الإجابة:", style: TextStyle(color: Colors.blue[800], fontWeight: FontWeight.bold, fontSize: 12)),
                              SizedBox(height: 4),
                              Text(q['explanation'] ?? "", style: TextStyle(color: Colors.blue[900], fontSize: 13)),
                            ],
                          ),
                        )
                    ],
                  ),
                ),
              );
            }),
            
            if (!_quizSubmitted) 
              SizedBox(width: double.infinity, child: ElevatedButton(onPressed: _submitQuiz, child: Text("تسليم الإجابات"), style: ElevatedButton.styleFrom(padding: EdgeInsets.all(16), backgroundColor: Color(0xFF6C63FF), foregroundColor: Colors.white, shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(15))))),
            
            SizedBox(height: 30),
          ],
        ),
      ),
    );
  }
}