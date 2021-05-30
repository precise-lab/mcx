#!/usr/bin/perl

use CGI;
use strict;
use DBI;
use URI::Escape;
use JSON::PP;
use Digest::MD5 qw(md5_hex);

die if(not ($ENV{"HTTP_REFERER"} =~ /^https*:\/\/mcx\.space/));

my ($DBName,$DBUser,$DBPass,%DBErr,$dbh,$sth,$html,$page,$jobid,$savetime,$dbname,$md5key,$callback,$jobhash);
my $q = new CGI;
my %jobstatus=(0=>'queued',1=>'initiated',2=>'created',3=>'running',4=>'completed',5=>'deleted',6=>'failed',7=>'invalid',8=>'cancelled', 9=>'writing output');

# Default paths for storage of the job/simulation database and simulation work folders
# both folders must be symbolic links pointing to network-shared folders via NSF that
# are accessible from all Docker Swarm nodes. Autofs is strongly recommended.
# both folders shall NOT be located inside the web server folder, typiclaly located at "/var/www/html"

my $dbpath="/var/lib/mcxcloud/db";
my $workspace="/var/lib/mcxcloud/workspace";

$DBName="dbi:SQLite:dbname=$dbpath/mcxcloud.db";
$DBUser="";
$DBPass="";
%DBErr=(RaiseError=>0,PrintError=>1);
$savetime=time();
$jobid=uc(join "", map { unpack "H*", chr(rand(256)) } 1..20);
$callback='addlog';
if(&V("license") eq ''){
  $dbname="mcxcloud";
}else{
  $dbname="mcxpub";
}

print "Content-Type: application/javascript\n\n";

if(&V("callback") ne ''){
    $callback=&V("callback");
}

# for stability, we are setting a few limitations to the simulations submitted
# if you are building a private mcx cloud, please disable the below if-block 
# by adding "&& false" in the condition

if(&V('json') =~/"RNGSeed"/){
   checklimit(decode_json(&V('json')));
}


if(&V("hash") ne '' && &V("id") ne ''){  # loading simulation JSON when one clicks on "Load" in the Browse tab
    my $ct=&V("id");
    my $key=&V("hash");
    $dbname='mcxpub';
    $dbh=DBI->connect($DBName,$DBUser,$DBPass,\%DBErr) or die($DBI::errstr);
    $sth=$dbh->selectall_arrayref("select json from $dbname where time=$ct and hash='$key';");
    my $jsondata='';
    if(defined $sth->[0]){
        foreach my $rec (@{$sth}){
            ($jsondata)=@$rec;
        }
    }
    my %response=('status'=>"success",'hash'=>$key, 'json'=>$jsondata);
    $html =$callback.'('.JSON::PP->new->utf8->encode(\%response).")\n";
    $dbh->disconnect() or die($DBI::errstr);
}elsif(&V("limit") ne ''){  # search and load simulation library in the Browse tab
    my $offset=&V("offset");
    $dbname='mcxpub';
    $dbh=DBI->connect($DBName,$DBUser,$DBPass,\%DBErr) or die($DBI::errstr);
    if(&V("keyword") eq ''){ # when a user searches the database without a keyword, search all records sorted by the runcount
        $sth=$dbh->selectall_arrayref("select time,hash,title,comment,license,thumbnail,runcount from $dbname order by runcount desc limit ".&V("limit")." offset $offset;");
    }else{ # when a user type a search keyword, search the title/comment field
        my $k=&V("keyword");
        $sth=$dbh->selectall_arrayref("select time,hash,title,comment,license,thumbnail,runcount from $dbname where title like '%$k%' or comment like '%$k%' limit ".&V("limit")." offset $offset;");
    }
    my @res=();
    if(defined $sth->[0]){
        foreach my $rec (@{$sth}){
            my ($id,$key,$title,$comment,$lic,$thumb)=@$rec;
            my %simu=('time'=>$id,'hash'=>$key,'title'=>$title,'comment'=>$comment,'license'=>$lic,'thumbnail'=>$thumb);
            push( @res, \%simu );
        }
    }
    $html =$callback.'('.JSON::PP->new->utf8->encode(\@res).")\n";
    $dbh->disconnect() or die($DBI::errstr);
}elsif($dbname eq 'mcxpub'){  # submit a new simulation to the library via the Share tab
    $dbh=DBI->connect($DBName,$DBUser,$DBPass,\%DBErr) or die($DBI::errstr);
    $md5key=md5_hex(&V("json"));
    if(&V("title") =~ /^(.*)\{ID=(\d+)\}$/){  # for admin use to update entry
        $sth=$dbh->prepare("update $dbname set title=?,comment=?,license=?,name=?,inst=?,email=?,netname=?,json=?,thumbnail=? where time = $2");
        $sth->execute($1,&V("comment"),&V("license"),&V("name"),&V("inst"),&V("email"),&V("netname"),&V("json"),&V("thumbnail"));
    }else{
        $sth=$dbh->prepare("insert into $dbname (time,title,comment,license,name,inst,email,netname,json,thumbnail,hash,createtime,ip) values (?,?,?,?,?,?,?,?,?,?,?,?,?)");
        $sth->execute($savetime,&V("title"),&V("comment"),&V("license"),&V("name"),&V("inst"),&V("email"),&V("netname"),&V("json"),&V("thumbnail"),$md5key,$savetime,$ENV{"REMOTE_ADDR"});
    }
    $html =$callback.'({"status":"success","createtime":"'.$savetime.'","hash":"'.$md5key.'","dberror":"'.$DBI::errstr.'"})'."\n";
    $dbh->disconnect() or die($DBI::errstr);
}elsif(&V("email") ne '' && &V("json") ne ''){  # add user submitted simulation in the Run tab to the processing queue
    $dbh=DBI->connect($DBName,$DBUser,$DBPass,\%DBErr) or die($DBI::errstr);
    $md5key=md5_hex(&V("json"));
    $sth=$dbh->prepare("insert into $dbname (time,name,inst,email,netname,json,jobid,hash,status,priority,ip) values (?,?,?,?,?,?,?,?,?,?,?)");
    $sth->execute($savetime,&V("name"),&V("inst"),&V("email"),&V("netname"),&V("json"),$jobid,$md5key,1,50,$ENV{"REMOTE_ADDR"});
    $html =$callback.'({"status":"success","jobid":"'.$jobid.'","hash":"'.$md5key.'","dberror":"'.$DBI::errstr.'"})'."\n";

    # update library
    $sth=$dbh->prepare("update mcxpub set runcount = ifnull(runcount,0) + 1 where hash = '".$md5key."'");
    $sth->execute();

    $dbh->disconnect() or die($DBI::errstr);
}elsif(&V("action") eq 'cancel'){  # cancel a previously submitted simulation in the Run tab
    $jobid=&V("jobid");
    $dbh=DBI->connect($DBName,$DBUser,$DBPass,\%DBErr) or die($DBI::errstr);
    $sth=$dbh->prepare("update $dbname set status=8 where jobid='$jobid';")
                 or die "Couldn't prepare statement: ";
    $sth->execute();
    $dbh->disconnect();
    $html =$callback.'({"status":"cancelled","jobid":"'.$jobid.'","dberror":"'.$DBI::errstr.'"})'."\n";
}else{ # respond to the inquiries of job status after a job is submitted in the Run tab
    my ($status,$output,$log);
    $status=7;
    $jobid=&V("jobid");
    $jobhash="_".&V("hash");
    if($jobid ne '' && not (-d "$workspace/$jobid") && $jobhash ne '' && (-d "$workspace/$jobhash") ){ # search to see if a simulation is cached, if yes, load cache first
        $jobid=$jobhash;
    }
    if(-e "$workspace/$jobid/output.jnii" && not -z "$workspace/$jobid/output.jnii"){  # if the output is generated or being written, wait it to finish and return result
        $status=9;
        if(-e "$workspace/$jobid/done"){ # when simulation is done
          open FF, "<$workspace/$jobid/output.jnii" || die("can not open log file");
          chomp(my @lines = <FF>);
          close(FF);
          my $outstr=join(/\n/,@lines);
          my $logstr="";
          if(-e "$workspace/$jobid/output.log" && not -z "$workspace/$jobid/output.log"){ # if log file is completed, return the mcx simulation log
              open FF, "<$workspace/$jobid/output.log" || die("can not open log file");
              chomp(my @logs = <FF>);
              close(FF);
              $logstr=join("\n",@logs);
          }
          $status=4;
          my %response=('status'=>$jobstatus{$status}, 'jobid'=>$jobid, 'output'=>$outstr, 'log'=>$logstr);
          $html =$callback.'('.JSON::PP->new->utf8->encode(\%response).")\n";
        }else{ # when the output file is currently being written
          $status=3;
          my %response=('status'=>$jobstatus{$status}, 'jobid'=>$jobid);
          $html =$callback.'('.JSON::PP->new->utf8->encode(\%response).")\n";
        }
    }elsif(-e "$workspace/$jobid/input.json" && not -z "$workspace/$jobid/input.json"){ # when a job is started, the input file is written to the work folder
        $status=2;
        $html =$callback.'({"status":"'.$jobstatus{$status}.'","jobid":"'.$jobid.'"})'."\n";
    }elsif($jobid ne '' && -d "$workspace/$jobid"){ # when a job folder is just created, but no input file is written
        $status=1;
        $html =$callback.'({"status":"'.$jobstatus{$status}.'","jobid":"'.$jobid.'"})'."\n";
    }else{ # use the database to inqure the last updated status
        my $cmd="select status from $dbname where jobid='$jobid';";
        $dbh=DBI->connect($DBName,$DBUser,$DBPass,\%DBErr) or die($DBI::errstr);
        $sth=$dbh->selectall_arrayref("select status from $dbname where jobid='$jobid';");
        if(defined $sth->[0]){
           $status=join(//,@{$sth->[0]});
        }
        $html =$callback.'({"status":"'.$jobstatus{$status}.'","jobid":"'.$jobid.'"})'."\n";
        $dbh->disconnect() or die($DBI::errstr);
    }
}

print $html;

sub V{
    my ($id)=@_;
    my $val=$q->param($id);
    $val=~ s/\+/ /g;
    return uri_unescape($val);
}

sub checklimit{
  my ($req)=@_;
  my $html;
  if($req->{'Session'}->{'Photons'}>=1e7){
     $html =$callback.'({"status":"invalid","jobid":"'.$jobid.'","dberror":"the max photon number is limited to 1e7 in this preview version"})'."\n";
  }
  if($html eq '' && defined($req->{'Session'}->{'DebugFlag'}) && $req->{'Session'}->{'DebugFlag'} =~ /m/i){
     $html =$callback.'({"status":"invalid","jobid":"'.$jobid.'","dberror":"storing photon trajectories is not supported in this preview version"})'."\n";
  }
  if($html eq '' && ($req->{'Forward'}->{'T1'}/$req->{'Forward'}->{'Dt'})>20){
     $html =$callback.'({"status":"invalid","jobid":"'.$jobid.'","dberror":"the maximum time gate number is limited to 20 in this preview version"})'."\n";
  }
  if($html eq '' && @{$req->{'Domain'}->{'Dim'}} == 3){
     foreach my $len (@{$req->{'Domain'}->{'Dim'}}){
       if($len>100){
         $html =$callback.'({"status":"invalid","jobid":"'.$jobid.'","dberror":"the maximum domain dimension is 100 in this preview version"})'."\n";
         last;
       }
     }
  }
  if($html eq '' && @{$req->{'Shapes'}} > 1){
     foreach my $obj (@{$req->{'Shapes'}}){
       if(defined($obj->{'Grid'})){
         foreach my $len (@{$obj->{'Grid'}->{'Size'}}){
            if($len>100){
                $html =$callback.'({"status":"invalid","jobid":"'.$jobid.'","dberror":"the maximum domain dimension is 100 in this preview version"})'."\n";
                last;
            }
         }
         last if $html ne '';
       }
     }
  }
  if($html eq '' && @{$req->{'Domain'}->{'Media'}} > 1){
     foreach my $obj (@{$req->{'Domain'}->{'Media'}}){
       if(defined($obj->{'mus'}) && $obj->{'mus'}>20){
           $html =$callback.'({"status":"invalid","jobid":"'.$jobid.'","dberror":"scattering coeff (mus) is limited to 20/mm in this preview version"})'."\n";
           last;
       }
     }
  }
  if($html ne ''){
     print $html;
     exit;
  }
}