import 'dart:async';
import 'package:flutter/material.dart';
import '../services/api_service.dart';
import 'student_detail_page.dart';

class StudentSearchPage extends StatefulWidget {
  const StudentSearchPage({super.key});

  @override
  State<StudentSearchPage> createState() => _StudentSearchPageState();
}

class _StudentSearchPageState extends State<StudentSearchPage> {
  final ApiService _api = ApiService();
  final TextEditingController _controller = TextEditingController();
  Timer? _debounce;

  bool _isLoading = false;
  String? _error;
  List<Map<String, dynamic>> _results = [];

  @override
  void dispose() {
    _debounce?.cancel();
    _controller.dispose();
    super.dispose();
  }

  void _onQueryChanged(String value) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 300), () {
      _search(value.trim());
    });
  }

  Future<void> _search(String query) async {
    if (query.isEmpty) {
      setState(() {
        _results = [];
        _error = null;
        _isLoading = false;
      });
      return;
    }

    setState(() {
      _isLoading = true;
      _error = null;
    });

    try {
      final results = await _api.searchStudents(query);
      setState(() {
        _results = results;
        _isLoading = false;
      });
    } catch (e) {
      setState(() {
        _error = e.toString();
        _isLoading = false;
      });
    }
  }

  void _openDetail(String studentId) {
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => StudentDetailPage(studentId: studentId),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Student Search')),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          children: [
            TextField(
              controller: _controller,
              onChanged: _onQueryChanged,
              decoration: const InputDecoration(
                hintText: 'Search by name, ID, or program',
                prefixIcon: Icon(Icons.search),
              ),
            ),
            const SizedBox(height: 16),
            if (_isLoading) const LinearProgressIndicator(),
            if (_error != null) ...[
              const SizedBox(height: 8),
              Text(
                _error!,
                style: const TextStyle(color: Colors.red),
              ),
            ],
            const SizedBox(height: 8),
            Expanded(
              child: _results.isEmpty && !_isLoading
                  ? const Center(child: Text('No results'))
                  : ListView.builder(
                      itemCount: _results.length,
                      itemBuilder: (context, index) {
                        final student = _results[index];
                        final name = student['name']?.toString() ?? '';
                        final studentId =
                            student['student_id']?.toString() ?? '';
                        return ListTile(
                          title: Text(name),
                          subtitle: Text(studentId),
                          onTap: studentId.isEmpty
                              ? null
                              : () => _openDetail(studentId),
                        );
                      },
                    ),
            ),
          ],
        ),
      ),
    );
  }
}
