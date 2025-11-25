import 'dart:io';
import 'package:flutter/material.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:image_picker/image_picker.dart';
import 'package:firebase_storage/firebase_storage.dart';
import 'package:animate_do/animate_do.dart';
import 'login_screen.dart';
import 'main.dart'; 

class ProfileSettingsScreen extends StatefulWidget {
  @override
  _ProfileSettingsScreenState createState() => _ProfileSettingsScreenState();
}

class _ProfileSettingsScreenState extends State<ProfileSettingsScreen> {
  final User? user = FirebaseAuth.instance.currentUser;
  final _nameController = TextEditingController();
  final _passController = TextEditingController();
  
  File? _imageFile;
  bool _isLoading = false;
  bool _obscurePassword = true;
  bool _deletePhoto = false; // لتتبع طلب حذف الصورة
  String? _currentPhotoUrl;

  @override
  void initState() {
    super.initState();
    _loadUserData();
  }

  Future<void> _loadUserData() async {
    if (user != null) {
      var doc = await FirebaseFirestore.instance.collection('users').doc(user!.uid).get();
      if (doc.exists) {
        setState(() {
          _nameController.text = doc.data()?['name'] ?? "";
          _currentPhotoUrl = doc.data()?['photoUrl'];
        });
      }
    }
  }

  // اختيار صورة أو حذفها
  void _showImageOptions() {
    showModalBottomSheet(
      context: context,
      builder: (ctx) => Container(
        padding: EdgeInsets.all(20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: Icon(Icons.photo_library, color: Color(0xFF6C63FF)),
              title: Text("اختر من المعرض"),
              onTap: () async {
                Navigator.pop(ctx);
                final picked = await ImagePicker().pickImage(source: ImageSource.gallery, imageQuality: 50);
                if (picked != null) {
                  setState(() {
                    _imageFile = File(picked.path);
                    _deletePhoto = false;
                  });
                }
              },
            ),
            if (_currentPhotoUrl != null || _imageFile != null)
              ListTile(
                leading: Icon(Icons.delete, color: Colors.red),
                title: Text("حذف الصورة الحالية", style: TextStyle(color: Colors.red)),
                onTap: () {
                  Navigator.pop(ctx);
                  setState(() {
                    _imageFile = null;
                    _deletePhoto = true;
                  });
                },
              ),
          ],
        ),
      ),
    );
  }

  Future<void> _saveChanges() async {
    if (user == null) return;

    // 1. التحقق من صحة المدخلات
    if (_nameController.text.trim().isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("يرجى إدخال الاسم"), backgroundColor: Colors.red));
      return;
    }
    if (_passController.text.isNotEmpty && _passController.text.length < 6) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("كلمة المرور يجب أن تكون 6 أحرف على الأقل"), backgroundColor: Colors.red));
      return;
    }

    setState(() => _isLoading = true);

    try {
      String? newPhotoUrl;
      
      // رفع الصورة الجديدة إذا وجدت
      if (_imageFile != null) {
        final ref = FirebaseStorage.instance.ref().child('user_images').child('${user!.uid}.jpg');
        await ref.putFile(_imageFile!);
        newPhotoUrl = await ref.getDownloadURL();
      }

      // تجهيز البيانات للتحديث
      Map<String, dynamic> data = {'name': _nameController.text.trim()};
      
      if (newPhotoUrl != null) {
        data['photoUrl'] = newPhotoUrl;
      } else if (_deletePhoto) {
        data['photoUrl'] = FieldValue.delete(); // حذف الحقل من فايربيز
      }
      
      await FirebaseFirestore.instance.collection('users').doc(user!.uid).update(data);

      // تحديث كلمة المرور
      if (_passController.text.isNotEmpty) {
        await user!.updatePassword(_passController.text);
      }

      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("تم حفظ التغييرات بنجاح ✅"), backgroundColor: Colors.green));
      if (mounted) Navigator.pop(context);

    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("خطأ: ${e.toString()}"), backgroundColor: Colors.red));
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  void _confirmLogout() {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text("تسجيل الخروج"),
        content: Text("هل أنت متأكد أنك تريد الخروج؟"),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: Text("إلغاء")),
          TextButton(
            onPressed: () async {
              Navigator.pop(ctx);
              await FirebaseAuth.instance.signOut();
              Navigator.pushAndRemoveUntil(context, MaterialPageRoute(builder: (_) => LoginScreen()), (route) => false);
            },
            child: Text("خروج", style: TextStyle(color: Colors.red, fontWeight: FontWeight.bold)),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    // تحديد الصورة المعروضة
    ImageProvider? bgImage;
    if (_imageFile != null) {
      bgImage = FileImage(_imageFile!);
    } else if (!_deletePhoto && _currentPhotoUrl != null) {
      bgImage = NetworkImage(_currentPhotoUrl!);
    }

    return Scaffold(
      appBar: AppBar(title: Text("الملف الشخصي والإعدادات"), centerTitle: true),
      body: SingleChildScrollView(
        padding: EdgeInsets.all(20),
        child: Column(
          children: [
            FadeInDown(
              child: Center(
                child: Stack(
                  children: [
                    Container(
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        border: Border.all(color: Color(0xFF6C63FF).withOpacity(0.5), width: 3),
                        boxShadow: [BoxShadow(color: Colors.black12, blurRadius: 10)]
                      ),
                      child: CircleAvatar(
                        radius: 65,
                        backgroundColor: Colors.grey[200],
                        backgroundImage: bgImage,
                        child: bgImage == null ? Icon(Icons.person, size: 65, color: Colors.grey) : null,
                      ),
                    ),
                    Positioned(
                      bottom: 0, right: 0,
                      child: GestureDetector(
                        onTap: _showImageOptions,
                        child: CircleAvatar(
                          backgroundColor: Color(0xFF6C63FF),
                          radius: 22,
                          child: Icon(Icons.camera_alt, size: 20, color: Colors.white),
                        ),
                      ),
                    )
                  ],
                ),
              ),
            ),
            SizedBox(height: 30),
            
            FadeInUp(
              child: Column(
                children: [
                  TextField(
                    controller: _nameController,
                    decoration: InputDecoration(
                      labelText: "الاسم الكامل", 
                      prefixIcon: Icon(Icons.person_outline), 
                      border: OutlineInputBorder(borderRadius: BorderRadius.circular(15))
                    ),
                  ),
                  SizedBox(height: 20),
                  TextField(
                    controller: _passController,
                    obscureText: _obscurePassword,
                    decoration: InputDecoration(
                      labelText: "كلمة مرور جديدة (اختياري)", 
                      prefixIcon: Icon(Icons.lock_outline), 
                      suffixIcon: IconButton(
                        icon: Icon(_obscurePassword ? Icons.visibility_outlined : Icons.visibility_off_outlined),
                        onPressed: () => setState(() => _obscurePassword = !_obscurePassword),
                      ),
                      border: OutlineInputBorder(borderRadius: BorderRadius.circular(15))
                    ),
                  ),
                  SizedBox(height: 30),
                  
                  Container(
                    padding: EdgeInsets.symmetric(horizontal: 15, vertical: 5),
                    decoration: BoxDecoration(color: Theme.of(context).cardColor, borderRadius: BorderRadius.circular(15), boxShadow: [BoxShadow(color: Colors.black12, blurRadius: 5)]),
                    child: SwitchListTile(
                      title: Text("الوضع الليلي"),
                      secondary: Icon(Icons.dark_mode_rounded),
                      value: themeNotifier.value == ThemeMode.dark,
                      activeColor: Color(0xFF6C63FF),
                      onChanged: (val) {
                        themeNotifier.value = val ? ThemeMode.dark : ThemeMode.light;
                      },
                    ),
                  ),

                  SizedBox(height: 30),
                  SizedBox(
                    width: double.infinity,
                    height: 55,
                    child: ElevatedButton(
                      onPressed: _isLoading ? null : _saveChanges,
                      child: _isLoading ? CircularProgressIndicator(color: Colors.white) : Text("حفظ التغييرات", style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
                      style: ElevatedButton.styleFrom(backgroundColor: Color(0xFF6C63FF), foregroundColor: Colors.white, shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(15))),
                    ),
                  ),
                  
                  SizedBox(height: 15),
                  TextButton.icon(
                    onPressed: _confirmLogout,
                    icon: Icon(Icons.logout, color: Colors.red),
                    label: Text("تسجيل الخروج", style: TextStyle(color: Colors.red, fontWeight: FontWeight.bold)),
                  )
                ],
              ),
            )
          ],
        ),
      ),
    );
  }
}