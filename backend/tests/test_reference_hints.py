import pytest
from app.reference_hints import lookup_hints


def test_bert_reference_retains_title_and_explicit_arxiv_identifier():
    result=lookup_hints('Jacob Devlin, Ming-Wei Chang, Kenton Lee, and Kristina Toutanova. BERT: Pre-training of deep bidirectional transformers for language understanding. CoRR, abs/1810.04805, 2018.')
    assert result['title']=='BERT: Pre-training of deep bidirectional transformers for language understanding'
    assert result['identifiers']==[{'kind':'arXiv','value':'1810.04805'}]
    assert result['source_clues'][0]['evidence']=='CoRR'
    assert '未联网核验' in result['notice']
    assert not any('url' in item for item in result['source_clues'])


def test_no_venue_is_not_assumed_to_mean_arxiv_or_an_invented_journal():
    result=lookup_hints('Alec Radford, JeffWu, Rewon Child, David Luan, Dario Amodei, and Ilya Sutskever. Language models are unsupervised multitask learners. 2019.')
    assert result['title']=='Language models are unsupervised multitask learners'
    assert result['source_clues']==[] and result['identifiers']==[]
    assert all('arXiv' not in item and 'IEEE' not in item for item in result['suggested_places'])
    assert any('Google Scholar' in item for item in result['suggested_places'])


@pytest.mark.parametrize('venue,expected', [('IEEE Transactions on Software Engineering','IEEE Xplore'),('ACM, 2020','ACM Digital Library'),('Proceedings of ACL, 2021','ACL Anthology'),('Advances in Neural Information Processing Systems','NeurIPS Proceedings'),('ICML, PMLR','PMLR'),('ICLR, 2023','OpenReview')])
def test_explicit_venues_provide_platform_specific_hints(venue,expected):
    result=lookup_hints('A. Author and B. Writer. A reference with a meaningful scientific title. '+venue+'.')
    assert result['title']=='A reference with a meaningful scientific title'
    assert any(expected in item for item in result['suggested_places'])
    assert all(item['basis']=='条目原文线索' for item in result['source_clues'])


def test_doi_publisher_is_explicitly_labelled_as_inference():
    result=lookup_hints('J. Author. A scientific reference for testing. doi:10.1109/TEST.2020.1234567.')
    assert result['identifiers'][0]['value']=='10.1109/TEST.2020.1234567'
    assert result['source_clues'][0]['basis']=='标识符推测，未核验'
    explicit=lookup_hints('J. Author. A scientific reference for testing. IEEE, doi:10.1109/TEST.2020.1234567.')
    assert len(explicit['source_clues'])==1


def test_author_initials_and_et_al_do_not_become_the_title():
    for prefix in ['J. D. Author, A. B. Writer', 'John Smith et al', 'John Smith']:
        result=lookup_hints(prefix+'. A controlled study of scientific retrieval. 2020.')
        assert result['title']=='A controlled study of scientific retrieval'
    assert lookup_hints('J. D. Author. Layer normalization. arXiv:1607.06450, 2016.')['title']=='Layer normalization'


def test_unknown_reference_and_source_urls_do_not_fabricate_a_destination():
    result=lookup_hints('2019.')
    assert result['title'] is None and result['title_status']=='unavailable'
    assert result['source_clues']==[]
    result=lookup_hints('A. Author. A scientific technical report. https://example.org/report.html')
    assert result['source_clues'][0]['evidence']=='example.org'
    assert '未核验' in result['source_clues'][0]['basis']
    assert 'example.org' not in ' '.join(result['suggested_places'])


@pytest.mark.parametrize('raw,title', [
    ('Colin Raﬀel, Noam Shazeer, Adam Roberts, Katherine Lee, Sharan Narang, Michael Matena, Yanqi Zhou, Wei Li, and Peter J. Liu. Exploring the limits of transfer learning with a uniﬁed text-to-text transformer, 2019.', 'Exploring the limits of transfer learning with a unified text-to-text transformer'),
    ('M. Rhu, N. Gimelshein, J. Clemons, A. Zulﬁqar, and S. W. Keckler. vdnn: Virtualized deep neural networks for scalable, memory-eﬃcient neural network design. In IEEE/ACM MICRO, 2016.', 'vdnn: Virtualized deep neural networks for scalable, memory-efficient neural network design'),
    ('Shar Narasimhan. NVIDIA Clocks Worlds Fastest BERT Training Time ... https://devblogs.nvidia.com/training-bert-with-gpus/, 2019.', 'NVIDIA Clocks Worlds Fastest BERT Training Time'),
])
def test_real_pdf_ligatures_author_lists_and_trailing_years(raw,title):
    assert lookup_hints(raw)['title'] == title
