import 'package:flutter/material.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:animate_do/animate_do.dart';

class ContentManager extends StatefulWidget {
  @override
  _ContentManagerState createState() => _ContentManagerState();
}

class _ContentManagerState extends State<ContentManager> {
  bool _isUploading = false;
  final TextEditingController _searchController = TextEditingController();
  String _searchQuery = "";

  // --- القائمة الذهبية (للرفع مرة واحدة فقط) ---
  final List<Map<String, dynamic>> _goldenCourses = [
    // ... (نفس القائمة السابقة)
    {
      "title": "Flutter الكامل (وائل أبو حمزة)", "instructor": "م. وائل أبو حمزة",
      "link": "https://youtube.com/playlist?list=PLw6Y5u47CYq47oDw63bMqkq06fjuoK_GJ",
      "lecturesCount": 35, "category": "mobile", "description": "المرجع العربي الأقوى. يبدأ من لغة Dart ثم ينتقل لأساسيات Flutter."
    },
    {
      "title": "Android Native (Kotlin)", "instructor": "م. محمد إبراهيم",
      "link": "https://youtube.com/playlist?list=PLlxmoA0rQ-Lw5k_QCqVl3rsoJOnb_00UV",
      "lecturesCount": 120, "category": "mobile", "description": "دورة شاملة لتطوير تطبيقات الأندرويد بلغة Kotlin."
    },
    {
      "title": "تأسيس الويب (HTML/CSS)", "instructor": "Nour Homsi",
      "link": "https://youtube.com/playlist?list=PLU0wE7dsJI8QWlkQphNZXMICIDo6u5IWR",
      "lecturesCount": 50, "category": "web", "description": "البداية الصحيحة لأي مطور ويب. تعلم هيكلة الصفحات وتنسيقها."
    },
    {
      "title": "Python (من الصفر)", "instructor": "Elzero Web School",
      "link": "https://youtube.com/playlist?list=PLDoPjvoNmBAyE_gei5d18qkfIe-Z8mocs",
      "lecturesCount": 150, "category": "ai", "description": "تعلم بايثون، لغة العصر، من الصفر وحتى الاحتراف."
    },
    {
      "title": "شبكات (CCNA) كامل", "instructor": "Ahmed Nazmy",
      "link": "https://youtube.com/playlist?list=PLpwHU9rNXAVurp2h2Jh-cd4-8XjkT5osu",
      "lecturesCount": 90, "category": "security", "description": "افهم كيف يعمل الإنترنت. شرح منهج سيسكو CCNA."
    },
    {
      "title": "الخوارزميات (Algorithms)", "instructor": "Adel Nasim",
      "link": "https://youtube.com/playlist?list=PLMDrOnfT8EAjT0lBMcmTiRWeaVqKXH5WC",
      "lecturesCount": 40, "category": "cs", "description": "شرح قوي للخوارزميات وهياكل البيانات."
    },
  ];

  Future<void> _uploadGoldenCourses() async {
    setState(() => _isUploading = true);
    // ... (نفس منطق الرفع السابق)
    int count = 0;
    for (var course in _goldenCourses) {
      await FirebaseFirestore.instance.collection('lessons').add({
        ...course,
        'type': 'Video',
        'createdAt': FieldValue.serverTimestamp(),
        'author': "نظام يُسر",
      });
      count++;
    }
    setState(() => _isUploading = false);
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("تم رفع $count كورس بنجاح لقاعدة البيانات!"), backgroundColor: Colors.green));
  }

  // --- دالة نموذج الإضافة والتعديل الموحد ---
  void _showCourseSheet(BuildContext context, {DocumentSnapshot? docToEdit}) {
    final bool isEditing = docToEdit != null;
    final Map<String, dynamic> initialData = isEditing ? docToEdit.data() as Map<String, dynamic> : {};
    
    final _titleController = TextEditingController(text: initialData['title'] ?? '');
    final _descController = TextEditingController(text: initialData['description'] ?? '');
    final _linkController = TextEditingController(text: initialData['link'] ?? '');
    final _countController = TextEditingController(text: (initialData['lecturesCount'] ?? 10).toString());
    String _selectedCategory = initialData['category'] ?? "mobile";

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (ctx) {
        final isDark = Theme.of(context).brightness == Brightness.dark;
        return StatefulBuilder(
          builder: (context, setSheetState) {
            return Container(
              height: MediaQuery.of(context).size.height * 0.85,
              decoration: BoxDecoration(color: Theme.of(context).cardColor, borderRadius: BorderRadius.vertical(top: Radius.circular(30))),
              padding: EdgeInsets.fromLTRB(25, 25, 25, MediaQuery.of(context).viewInsets.bottom + 20),
              child: SingleChildScrollView(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Center(child: Container(width: 50, height: 5, decoration: BoxDecoration(color: Colors.grey[300], borderRadius: BorderRadius.circular(10)))),
                    SizedBox(height: 25),
                    Text(isEditing ? "تعديل الكورس" : "إضافة كورس جديد", style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold, color: Color(0xFF6C63FF))),
                    SizedBox(height: 20),

                    _buildInput(_titleController, "عنوان الكورس", isDark),
                    SizedBox(height: 15),
                    _buildInput(_descController, "وصف الكورس (يظهر للطالب)", isDark, maxLines: 3),
                    SizedBox(height: 15),
                    _buildInput(_linkController, "رابط قائمة التشغيل", isDark),
                    SizedBox(height: 15),
                    
                    Row(
                      children: [
                        Expanded(child: _buildInput(_countController, "عدد الدروس", isDark, isNumber: true)),
                        SizedBox(width: 15),
                        Expanded(
                          child: DropdownButtonFormField(
                            value: _selectedCategory,
                            dropdownColor: Theme.of(context).cardColor,
                            style: TextStyle(color: isDark ? Colors.white : Colors.black),
                            items: ["mobile","web","ai","security","cs","game","other"].map((e)=>DropdownMenuItem(value: e, child: Text(e))).toList(),
                            onChanged: (v)=> _selectedCategory=v.toString(),
                            decoration: InputDecoration(filled: true, fillColor: isDark ? Colors.black26 : Colors.grey[50], border: OutlineInputBorder(borderRadius: BorderRadius.circular(15), borderSide: BorderSide.none)),
                          ),
                        )
                      ],
                    ),
                    SizedBox(height: 30),
                    SizedBox(
                      width: double.infinity, 
                      height: 50, 
                      child: ElevatedButton(
                        onPressed: () async {
                           final data = {
                             'title': _titleController.text, 'description': _descController.text, 'link': _linkController.text,
                             'lecturesCount': int.tryParse(_countController.text)??10, 'category': _selectedCategory,
                           };
                           if (isEditing) {
                             await docToEdit!.reference.update({...data, 'updatedAt': FieldValue.serverTimestamp()});
                             ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("تم تعديل الكورس")));
                           } else {
                             await FirebaseFirestore.instance.collection('lessons').add({...data, 'createdAt': FieldValue.serverTimestamp(), 'author': "المعلم"});
                             ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("تم نشر الكورس")));
                           }
                           Navigator.pop(ctx);
                        }, 
                        child: Text(isEditing ? "حفظ التعديلات" : "نشر الكورس"), 
                        style: ElevatedButton.styleFrom(backgroundColor: Color(0xFF6C63FF), foregroundColor: Colors.white)
                      )
                    )
                  ],
                ),
              ),
            );
          }
        );
      },
    );
  }

  // دالة مساعدة لتنسيق حقول الإدخال
  Widget _buildInput(TextEditingController controller, String label, bool isDark, {int maxLines = 1, bool isNumber = false}) {
    return TextField(
      controller: controller,
      style: TextStyle(color: isDark ? Colors.white : Colors.black),
      maxLines: maxLines,
      keyboardType: isNumber ? TextInputType.number : TextInputType.text,
      decoration: InputDecoration(
        labelText: label,
        labelStyle: TextStyle(color: Colors.grey),
        filled: true,
        fillColor: isDark ? Colors.black26 : Colors.grey[50],
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(15), borderSide: BorderSide.none)
      ),
    );
  }

  // دالة تأكيد الحذف
  void _confirmDelete(BuildContext context, DocumentReference docRef) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text("تأكيد الحذف"),
        content: Text("هل أنت متأكد من حذف هذا الكورس بالكامل؟"),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: Text("إلغاء")),
          ElevatedButton(
            onPressed: () {
              docRef.delete();
              Navigator.pop(ctx);
              ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("تم الحذف")));
            },
            child: Text("حذف"),
            style: ElevatedButton.styleFrom(backgroundColor: Colors.red, foregroundColor: Colors.white),
          ),
        ],
      ),
    );
  }


  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final textColor = isDark ? Colors.white : Colors.black87;
    final cardColor = Theme.of(context).cardColor;

    return Scaffold(
      backgroundColor: Theme.of(context).scaffoldBackgroundColor,
      appBar: AppBar(
        title: Text("إدارة المحتوى", style: TextStyle(color: textColor)), 
        centerTitle: true,
        iconTheme: IconThemeData(color: textColor),
        // زر رفع الكورسات الـ Golden
        actions: [
          IconButton(
            icon: Icon(Icons.upload_file, color: Colors.orange),
            onPressed: _isUploading ? null : _uploadGoldenCourses,
            tooltip: "رفع الكورسات الأساسية مرة واحدة",
          ),
        ],
      ),
      body: Column(
        children: [
          // شريط البحث (الميزة الجديدة)
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 10, 20, 10),
            child: TextField(
              controller: _searchController,
              onChanged: (value) => setState(() => _searchQuery = value.toLowerCase()),
              style: TextStyle(color: textColor),
              decoration: InputDecoration(
                hintText: "ابحث عن كورس...",
                hintStyle: TextStyle(color: Colors.grey),
                prefixIcon: Icon(Icons.search, color: Color(0xFF6C63FF)),
                filled: true,
                fillColor: cardColor,
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(15), borderSide: BorderSide.none),
              ),
            ),
          ),
          
          Expanded(
            child: StreamBuilder<QuerySnapshot>(
              stream: FirebaseFirestore.instance.collection('lessons').orderBy('createdAt', descending: true).snapshots(),
              builder: (context, snapshot) {
                if (!snapshot.hasData) return Center(child: CircularProgressIndicator());
                
                var filteredDocs = snapshot.data!.docs.where((doc) {
                  var title = (doc['title'] ?? "").toString().toLowerCase();
                  return title.contains(_searchQuery);
                }).toList();

                if (filteredDocs.isEmpty) return Center(child: Text("لا توجد كورسات مطابقة.", style: TextStyle(color: Colors.grey)));

                return ListView.builder(
                  padding: EdgeInsets.fromLTRB(20, 0, 20, 80),
                  itemCount: filteredDocs.length,
                  itemBuilder: (ctx, i) {
                    var doc = filteredDocs[i];
                    var data = doc.data() as Map<String, dynamic>;
                    String description = data['description'] ?? 'لا يوجد وصف.';
                    int lectureCount = data['lecturesCount'] ?? 0;
                    
                    return FadeInUp(
                      child: Container(
                        margin: EdgeInsets.only(bottom: 10),
                        decoration: BoxDecoration(
                          color: cardColor,
                          borderRadius: BorderRadius.circular(15),
                          boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 5)],
                        ),
                        child: ListTile(
                          contentPadding: EdgeInsets.symmetric(horizontal: 20, vertical: 15),
                          leading: Icon(Icons.video_library, color: Color(0xFF6C63FF), size: 30),
                          title: Text(data['title'] ?? "", style: TextStyle(color: textColor, fontWeight: FontWeight.bold)),
                          subtitle: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              SizedBox(height: 5),
                              Text(description.length > 50 ? description.substring(0, 50) + "..." : description, style: TextStyle(color: Colors.grey, fontSize: 12)),
                              SizedBox(height: 5),
                              Text("${lectureCount} درس", style: TextStyle(color: Color(0xFF6C63FF), fontWeight: FontWeight.bold, fontSize: 12)),
                            ],
                          ),
                          trailing: PopupMenuButton<String>(
                            onSelected: (value) {
                              if (value == 'edit') {
                                _showCourseSheet(context, docToEdit: doc);
                              } else if (value == 'delete') {
                                _confirmDelete(context, doc.reference);
                              }
                            },
                            itemBuilder: (BuildContext context) => <PopupMenuEntry<String>>[
                              PopupMenuItem<String>(value: 'edit', child: Row(children: [Icon(Icons.edit, color: Color(0xFF6C63FF)), SizedBox(width: 8), Text('تعديل')])),
                              PopupMenuItem<String>(value: 'delete', child: Row(children: [Icon(Icons.delete, color: Colors.red), SizedBox(width: 8), Text('حذف')])),
                            ],
                          ),
                        ),
                      ),
                    );
                  },
                );
              },
            ),
          ),
        ],
      ),
      bottomNavigationBar: Container(
        padding: EdgeInsets.all(20),
        decoration: BoxDecoration(color: cardColor, boxShadow: [BoxShadow(color: Colors.black12, blurRadius: 20, offset: Offset(0, -5))]),
        child: ElevatedButton.icon(
          onPressed: () => _showCourseSheet(context), 
          icon: Icon(Icons.add), 
          label: Text("إضافة كورس يدوي"),
          style: ElevatedButton.styleFrom(backgroundColor: Color(0xFF6C63FF), foregroundColor: Colors.white, minimumSize: Size(double.infinity, 50))
        ),
      ),
    );
  }
}